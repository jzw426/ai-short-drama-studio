"""场景资产路由（M4-3）：场景四视图的读写与 AI 生成。

为什么需要这个模块：首帧/分镜的"场景一致性"此前只能靠 scene_ref 字符串，
同一场戏换几个机位就换了三种环境。这里把场景的 wide/medium/close/establishing
四张定场图落库（SceneAsset），首帧服务会读 wide/establishing 作为"场景参考"。

两个关键语义：
  * 同一 (project_id, scene_ref, view) 只有一张图 —— POST 是 upsert，重复上传覆盖
    而不是 500（唯一索引 uq_scene_assets_project_scene_view 保证库里也只有一行）；
  * source=ai 时按次计费：先预占配额，任何失败都退款（和 characters.py 的锁脸/
    三视图一致），绝不让失败请求白扣用户额度。
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota_and_commit
from app.models.project import Project
from app.models.scene_asset import SceneAsset
from app.models.user import User
from app.services.ai_service import (
    AIUnavailableError,
    ImageCapabilityError,
    ai_service,
)
from app.services.storage_service import persist_remote_media

router = APIRouter(tags=["Scene Assets"])
logger = logging.getLogger(__name__)

# 四视图：wide 定环境、medium 定场面、close 定质感、establishing 定空间关系
SCENE_VIEWS: tuple = ("wide", "medium", "close", "establishing")
SCENE_SOURCES: tuple = ("upload", "ai")


class SceneAssetUpsert(BaseModel):
    scene_ref: str = Field(min_length=1, max_length=255)
    view: str = "wide"
    # upload：前端已上传好，url 必填；ai：由后端出图并转存
    source: str = "upload"
    url: Optional[str] = Field(default=None, max_length=2048)
    prompt: Optional[str] = Field(default=None, max_length=2048)


class SceneAssetResponse(BaseModel):
    id: str
    project_id: str
    scene_ref: str
    view: str
    url: Optional[str] = None
    source: str
    prompt: Optional[str] = None


async def _get_project_or_404(
    project_id: str, owner_id: str, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == owner_id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _to_response(asset: SceneAsset) -> SceneAssetResponse:
    response = SceneAssetResponse.model_validate(asset, from_attributes=True)
    response.url = await signed_media_url(asset.url)
    return response


def _scene_prompt(scene_ref: str, view: str, prompt: Optional[str]) -> str:
    base = (prompt or "").strip() or f"场景 {scene_ref} 的定场画面"
    return f"{base}；{view} 视角；电影感构图，动漫漫剧风格，环境光线与配色统一"


async def _generate_scene_image(
    db: AsyncSession, project_id: str, user_id: str, prompt: str
) -> str:
    """出图 + 转存，失败一律退款。返回可入库的规范 URL。"""
    await acquire_ai_quota_or_429(db, user_id)
    try:
        image_urls = await ai_service.generate_image(
            prompt, user_id=user_id, project_id=project_id
        )
    except HTTPException:
        await refund_ai_quota_and_commit(db, user_id)
        raise
    except ImageCapabilityError as exc:
        await refund_ai_quota_and_commit(db, user_id)
        raise HTTPException(
            status_code=502, detail=f"场景图需要图生图能力，当前 provider 不支持：{exc}"
        ) from exc
    except AIUnavailableError as exc:
        await refund_ai_quota_and_commit(db, user_id)
        raise HTTPException(status_code=503, detail=f"AI 场景图生成失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 兜底退款
        await refund_ai_quota_and_commit(db, user_id)
        raise HTTPException(status_code=503, detail=f"AI 场景图生成失败：{exc}") from exc

    if not image_urls:
        await refund_ai_quota_and_commit(db, user_id)
        raise HTTPException(status_code=503, detail="AI 场景图生成失败：未返回任何图片")

    image_url = str(image_urls[0])
    try:
        image_url = await persist_remote_media(
            image_url, f"ai/scenes/{project_id}/{uuid.uuid4()}"
        )
    except Exception as exc:  # noqa: BLE001 - 已付费的图不能丢
        logger.warning("场景图转存失败，回退第三方链接: %s (%s)", image_url[:120], exc)
    return image_url


@router.get(
    "/projects/{project_id}/scene-assets", response_model=List[SceneAssetResponse]
)
async def list_scene_assets(
    project_id: str,
    scene_ref: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出场景资产（可按 scene_ref 过滤）"""
    await _get_project_or_404(project_id, current_user.id, db)
    query = select(SceneAsset).where(SceneAsset.project_id == project_id)
    ref = (scene_ref or "").strip()
    if ref:
        query = query.where(SceneAsset.scene_ref == ref)
    query = query.order_by(SceneAsset.scene_ref, SceneAsset.view)
    rows = (await db.execute(query)).scalars().all()
    return [await _to_response(asset) for asset in rows]


@router.post(
    "/projects/{project_id}/scene-assets",
    response_model=SceneAssetResponse,
    status_code=201,
)
async def upsert_scene_asset(
    project_id: str,
    data: SceneAssetUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新建或覆盖某个场景的某个视角（同 project+scene_ref+view 唯一）"""
    await _get_project_or_404(project_id, current_user.id, db)

    scene_ref = (data.scene_ref or "").strip()
    if not scene_ref:
        raise HTTPException(status_code=400, detail="scene_ref 不能为空")
    view = (data.view or "").strip() or "wide"
    if view not in SCENE_VIEWS:
        raise HTTPException(
            status_code=400, detail=f"不支持的视角：{view}（可选 {'/'.join(SCENE_VIEWS)}）"
        )
    source = (data.source or "").strip() or "upload"
    if source not in SCENE_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"不支持的来源：{source}（可选 upload/ai）"
        )

    prompt_text = (data.prompt or "").strip() or None
    if source == "ai":
        prompt_text = _scene_prompt(scene_ref, view, prompt_text)
        url = await _generate_scene_image(db, project_id, current_user.id, prompt_text)
    else:
        url = (data.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="上传场景资产需要提供 url")
        try:
            # 外部链接统一转存；自家 /uploads 地址原样返回（幂等）
            url = await persist_remote_media(
                url, f"ai/scenes/{project_id}/{uuid.uuid4()}"
            )
        except Exception as exc:  # noqa: BLE001 - 转存失败仍允许先记录外部链接
            logger.warning("场景资产转存失败，保留原始链接: %s (%s)", url[:120], exc)

    existing = (
        await db.execute(
            select(SceneAsset).where(
                SceneAsset.project_id == project_id,
                SceneAsset.scene_ref == scene_ref,
                SceneAsset.view == view,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = SceneAsset(
            project_id=project_id, scene_ref=scene_ref, view=view
        )
        db.add(existing)
    # upsert：同视角重复提交时覆盖，而不是撞唯一索引 500
    existing.url = url
    existing.source = source
    existing.prompt = prompt_text

    await db.flush()
    await db.refresh(existing)
    return await _to_response(existing)


@router.delete("/projects/{project_id}/scene-assets/{asset_id}", status_code=204)
async def delete_scene_asset(
    project_id: str,
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除一张场景资产"""
    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(SceneAsset).where(
            SceneAsset.id == asset_id, SceneAsset.project_id == project_id
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="场景资产不存在")
    await db.delete(asset)
    await db.flush()
    return None
