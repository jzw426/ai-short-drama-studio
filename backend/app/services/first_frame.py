"""首帧图服务（M4-3）：分镜镜头 → 首帧画面。

为什么单独抽一层，而不是塞在路由里：

1. 首帧是**前置产物**。M4-3 起渲染任务不再同步调用付费视频生成
   （见 render_service._pick_source），视频走 ai_video_jobs 异步作业；
   而"图生视频"的入口正是一张首帧图 —— 没有首帧，后面整条链路都是空的。
2. 首帧要同时消费三类上下文：镜头自身（description / camera_angle / scene_ref）、
   M4-2 的角色锁脸资产（reference_image_url / image_seed / visual_prompt）、
   场景四视图（SceneAsset 的 wide / establishing 定场图）。这些拼装规则如果散在
   路由里，前端"重新生成"和批量补图会各拼一套，同一个镜头出现两种画风。
3. 计费口径要统一：一次出图 = 一次配额，失败必须退款；这条逻辑和 characters.py
   的锁脸/三视图完全同构，集中在这里才能保证行为一致。

设计上刻意**不**给场景参考图：当前 provider 的 image edit 只吃单张参考图，
角色一致性优先（人脸跑偏比背景跑偏更出戏），场景只以文本"场景参考"进入 prompt。
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota_and_commit
from app.models.character import Character
from app.models.project import Project
from app.models.scene_asset import SceneAsset
from app.models.storyboard import Shot
from app.services.ai_service import (
    AIUnavailableError,
    ImageCapabilityError,
    ai_service,
)
from app.services.storage_service import persist_remote_media

logger = logging.getLogger(__name__)

# 只有"定场"性质的视角才能当场景参考：特写/中景会把构图锁死在人物身上
SCENE_REFERENCE_VIEWS: tuple = ("wide", "establishing")

# 所有首帧共用的画风尾巴：换成真人风格会跟角色卡（动漫漫剧）割裂
FRAME_STYLE = "电影分镜首帧，动漫漫剧风格，构图稳定、光线与配色统一"


async def _scene_reference(
    db: AsyncSession, project_id: str, scene_ref: Optional[str]
) -> Optional[SceneAsset]:
    """取该场景的定场参考（wide 优先，其次 establishing）。"""
    ref = (scene_ref or "").strip()
    if not ref:
        return None
    rows = (
        await db.execute(
            select(SceneAsset).where(
                SceneAsset.project_id == project_id,
                SceneAsset.scene_ref == ref,
                SceneAsset.view.in_(SCENE_REFERENCE_VIEWS),
            )
        )
    ).scalars().all()
    if not rows:
        return None
    for view in SCENE_REFERENCE_VIEWS:
        for asset in rows:
            if asset.view == view:
                return asset
    return rows[0]


def _character_fragment(character: Character) -> str:
    """把角色压成 prompt 里的一段外观约束。

    已锁脸的角色带 visual_prompt（结构化发型/服装/配色），是最强的一致性约束；
    没锁脸的退化成 name/gender/age/traits/description，只能保证"同一个名字像同一个人"。
    """
    name = (character.name or "角色").strip()
    visual = (character.visual_prompt or "").strip()
    if visual:
        return f"角色 {name}：与参考图同一角色；{visual}"

    bits: List[str] = [f"角色 {name}"]
    gender = (character.gender or "").strip()
    if gender and gender != "other":
        bits.append(gender)
    if character.age:
        bits.append(f"{int(character.age)}岁")
    traits = [str(t).strip() for t in (character.traits or []) if str(t).strip()]
    if traits:
        bits.append("性格外化：" + "、".join(traits[:5]))
    description = (character.description or "").strip()
    if description:
        bits.append("外形要点：" + description[:200])
    bits.append("动漫漫剧风格")
    return "；".join(bits)


def build_first_frame_prompt(
    shot: Shot,
    characters: Sequence[Character],
    scene_asset: Optional[SceneAsset] = None,
) -> str:
    """拼首帧 prompt。纯函数，方便测试直接断言内容。"""
    parts: List[str] = []
    header = f"镜头 {shot.shot_number}"
    label = (shot.label or "").strip()
    if label:
        header += f"（{label}）"
    parts.append(header)

    description = (shot.description or "").strip()
    if description:
        parts.append(f"画面：{description}")
    angle = (shot.camera_angle or "").strip()
    if angle:
        parts.append(f"运镜：{angle}")
    scene_ref = (shot.scene_ref or "").strip()
    if scene_ref:
        parts.append(f"场景：{scene_ref}")
    if scene_asset is not None:
        hint = (scene_asset.prompt or "").strip() or f"{scene_asset.view} 视角定场"
        parts.append(f"场景参考：{hint}")

    for character in characters:
        parts.append(_character_fragment(character))

    parts.append(FRAME_STYLE)
    return "；".join(p for p in parts if p)


async def load_shot_characters(
    db: AsyncSession, project_id: str, shot: Shot
) -> List[Character]:
    """按 shot.character_refs 解析出角色对象（同时支持 id 与名字，保持引用顺序）。

    前端历史上存过 id 也存过名字，两种都要认；顺序按 character_refs 保持稳定，
    否则同一镜头反复重出会因为角色顺序变化导致 prompt 抖动。
    """
    refs = [str(r).strip() for r in (shot.character_refs or []) if str(r).strip()]
    if not refs:
        return []
    rows = (
        await db.execute(
            select(Character).where(
                Character.project_id == project_id,
                or_(Character.id.in_(refs), Character.name.in_(refs)),
            )
        )
    ).scalars().all()
    by_id = {c.id: c for c in rows}
    by_name = {c.name: c for c in rows}
    ordered: List[Character] = []
    for ref in refs:
        character = by_id.get(ref) or by_name.get(ref)
        if character is not None and character not in ordered:
            ordered.append(character)
    return ordered


async def _project_owner_id(db: AsyncSession, project_id: str) -> Optional[str]:
    return (
        await db.execute(select(Project.owner_id).where(Project.id == project_id))
    ).scalar_one_or_none()


async def generate_first_frame(
    db: AsyncSession,
    project_id: str,
    shot: Shot,
    characters: Optional[Sequence[Character]] = None,
    *,
    regenerate: bool = False,
    user_id: Optional[str] = None,
) -> dict:
    """生成（或复用）一个镜头的首帧图，返回 {image_url, prompt, characters_used, reused}。

    计费：每次真正调用 AI 前预占一次配额，失败（含 provider 不支持图生图）全部退款并
    转成 502/503；AI_DAILY_QUOTA<=0 时 acquire 本身不限流，行为与 characters.py 一致。
    """
    chars = list(characters or [])
    characters_used = [c.name for c in chars if (c.name or "").strip()]
    scene_asset = await _scene_reference(db, project_id, shot.scene_ref)
    prompt = build_first_frame_prompt(shot, chars, scene_asset)

    existing = (shot.image_url or "").strip()
    if existing and not regenerate:
        # 已有首帧且没要求重出：直接复用，不碰配额也不打 provider
        return {
            "image_url": existing,
            "prompt": prompt,
            "characters_used": characters_used,
            "reused": True,
        }

    # 首个已锁脸的角色当参考图来源：一张参考图只能喂一个角色，主角优先（character_refs 顺序）
    locked: Optional[Character] = None
    for character in chars:
        if (character.reference_image_url or "").strip():
            locked = character
            break
    reference_image_url = (locked.reference_image_url or "").strip() if locked else None
    seed = locked.image_seed if locked is not None else None

    owner_id = user_id or await _project_owner_id(db, project_id)
    if not owner_id:
        # 配额是按用户记的，拿不到归属就没法计费，直接拒绝而不是白送一次出图
        raise HTTPException(status_code=400, detail="无法确定项目归属用户，不能生成首帧")

    await acquire_ai_quota_or_429(db, owner_id)

    try:
        image_urls = await ai_service.generate_image(
            prompt,
            reference_image_url=reference_image_url,
            seed=seed,
            user_id=owner_id,
            project_id=project_id,
        )
    except HTTPException:
        await refund_ai_quota_and_commit(db, owner_id)
        raise
    except ImageCapabilityError as exc:
        await refund_ai_quota_and_commit(db, owner_id)
        raise HTTPException(
            status_code=502,
            detail=f"首帧出图需要图生图能力，当前 provider 不支持：{exc}",
        ) from exc
    except AIUnavailableError as exc:
        await refund_ai_quota_and_commit(db, owner_id)
        raise HTTPException(status_code=503, detail=f"AI 首帧出图失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 兜底退款，避免配额被吞
        await refund_ai_quota_and_commit(db, owner_id)
        raise HTTPException(status_code=503, detail=f"AI 首帧出图失败：{exc}") from exc

    if not image_urls:
        await refund_ai_quota_and_commit(db, owner_id)
        raise HTTPException(status_code=503, detail="AI 首帧出图失败：未返回任何图片")

    image_url = str(image_urls[0])
    try:
        # 转存到自有存储：第三方临时链接会过期，而首帧后面要被图生视频反复读取
        image_url = await persist_remote_media(
            image_url, f"ai/frames/{project_id}/{uuid.uuid4()}"
        )
    except Exception as exc:  # noqa: BLE001 - 转存失败不该让已经付过费的图白丢
        logger.warning("首帧图转存失败，回退第三方链接: %s (%s)", image_url[:120], exc)

    shot.image_url = image_url
    await db.flush()

    return {
        "image_url": image_url,
        "prompt": prompt,
        "characters_used": characters_used,
        "reused": False,
    }
