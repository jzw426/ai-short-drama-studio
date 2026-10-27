from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.models.storyboard import Storyboard, Shot
from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota_and_commit
from app.services.ai_service import AIUnavailableError, ai_service
from app.services.first_frame import generate_first_frame, load_shot_characters
from app.models.project import Project
from app.models.user import User
from app.schemas.storyboard import (
    StoryboardUpdate, StoryboardResponse, ShotCreate, ShotUpdate, ShotResponse,
    FirstFrameRequest, FirstFrameResponse, VideoPromptUpdate,
)

router = APIRouter(tags=["Storyboards"])


async def _get_project_or_404(
    project_id: str, owner_id: str, db: AsyncSession
) -> Project:
    from sqlalchemy import select

    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == owner_id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _get_storyboard_or_create(
    project_id: str, owner_id: str, db: AsyncSession
) -> Storyboard:
    from sqlalchemy import select

    result = await db.execute(
        select(Storyboard).where(Storyboard.project_id == project_id)
    )
    storyboard = result.scalar_one_or_none()
    if not storyboard:
        await _get_project_or_404(project_id, owner_id, db)
        storyboard = Storyboard(project_id=project_id)
        db.add(storyboard)
        await db.flush()
        await db.refresh(storyboard)
    return storyboard


@router.get("/projects/{project_id}/storyboard", response_model=StoryboardResponse)
async def get_storyboard(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目分镜"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.project_id == project_id)
        .options(selectinload(Storyboard.shots))
    )
    storyboard = result.scalar_one_or_none()
    if not storyboard:
        storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
        result = await db.execute(
            select(Storyboard)
            .where(Storyboard.id == storyboard.id)
            .options(selectinload(Storyboard.shots))
        )
        storyboard = result.scalar_one()

    return await _storyboard_response(storyboard)


async def _shot_response(shot: Shot) -> ShotResponse:
    """ORM 镜头 → 响应模型，并把媒体字段换成可访问的签名链接。

    为什么要单独一步：库里存的是规范 URL（本地模式是 /uploads/...，对象存储是
    s3://bucket/key），直接吐给前端会 403/404；签名后前端才能预览首帧与素材。
    """
    response = ShotResponse.model_validate(shot)
    response.image_url = await signed_media_url(shot.image_url)
    response.video_url = await signed_media_url(shot.video_url)
    return response


async def _storyboard_response(storyboard: Storyboard) -> StoryboardResponse:
    response = StoryboardResponse.model_validate(storyboard)
    response.shots = [await _shot_response(shot) for shot in (storyboard.shots or [])]
    return response


async def _get_shot_or_404(
    db: AsyncSession, storyboard_id: str, shot_id: str
) -> Shot:
    from sqlalchemy import select

    result = await db.execute(
        select(Shot).where(Shot.id == shot_id, Shot.storyboard_id == storyboard_id)
    )
    shot = result.scalar_one_or_none()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return shot


@router.put("/projects/{project_id}/storyboard", response_model=StoryboardResponse)
async def update_storyboard(
    project_id: str,
    data: StoryboardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新分镜画布状态"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(storyboard, key, value)

    await db.flush()

    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.id == storyboard.id)
        .options(selectinload(Storyboard.shots))
    )
    return await _storyboard_response(result.scalar_one())


# ===== 镜头管理 =====

@router.get("/projects/{project_id}/storyboard/shots", response_model=List[ShotResponse])
async def list_shots(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有镜头"""
    from sqlalchemy import select

    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Shot)
        .where(Shot.storyboard_id == storyboard.id)
        .order_by(Shot.sort_order)
    )
    return [await _shot_response(shot) for shot in result.scalars().all()]


@router.post("/projects/{project_id}/storyboard/shots", response_model=ShotResponse, status_code=201)
async def create_shot(
    project_id: str,
    data: ShotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新镜头"""
    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)

    shot = Shot(
        storyboard_id=storyboard.id,
        shot_number=data.shot_number,
        label=data.label,
        description=data.description,
        duration=data.duration,
        camera_angle=data.camera_angle,
        transition=data.transition,
        scene_ref=data.scene_ref,
        character_refs=data.character_refs,
        video_url=data.video_url,
        image_url=data.image_url,
        video_prompt=data.video_prompt,
        sort_order=data.sort_order,
    )
    db.add(shot)
    await db.flush()
    await db.refresh(shot)
    return await _shot_response(shot)


@router.put("/projects/{project_id}/storyboard/shots/{shot_id}", response_model=ShotResponse)
async def update_shot(
    project_id: str,
    shot_id: str,
    data: ShotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新镜头"""
    from sqlalchemy import select

    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Shot).where(Shot.id == shot_id, Shot.storyboard_id == storyboard.id)
    )
    shot = result.scalar_one_or_none()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(shot, key, value)

    await db.flush()
    await db.refresh(shot)
    return await _shot_response(shot)


@router.post(
    "/projects/{project_id}/storyboard/shots/{shot_id}/first-frame",
    response_model=FirstFrameResponse,
)
async def generate_shot_first_frame(
    project_id: str,
    shot_id: str,
    data: FirstFrameRequest = FirstFrameRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成（或复用）镜头首帧图。

    首帧是图生视频的输入：前端"生成视频"按钮会先确保有这个产物，再提交异步
    AI 视频作业。默认 regenerate=False 表示"有就复用"，只有显式要求才重新出图并扣配额。
    """
    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    shot = await _get_shot_or_404(db, storyboard.id, shot_id)
    characters = await load_shot_characters(db, project_id, shot)
    result = await generate_first_frame(
        db,
        project_id,
        shot,
        characters,
        regenerate=bool(data.regenerate),
        user_id=current_user.id,
    )
    result["image_url"] = await signed_media_url(result.get("image_url"))
    return result


@router.post(
    "/projects/{project_id}/storyboard/shots/{shot_id}/video-prompt",
    response_model=ShotResponse,
)
async def update_shot_video_prompt(
    project_id: str,
    shot_id: str,
    data: VideoPromptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """固化该镜头的视频提示词。

    单独一个端点而不是复用 PUT shots/{id}：前端"生成视频"要一次性把提示词落库，
    走通用 PATCH 会把整个镜头所有字段一起写回，并发编辑时容易互相覆盖；
    这里只动 video_prompt 一个字段。
    """
    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    shot = await _get_shot_or_404(db, storyboard.id, shot_id)
    shot.video_prompt = (data.video_prompt or "").strip()
    await db.flush()
    await db.refresh(shot)
    return await _shot_response(shot)


@router.delete("/projects/{project_id}/storyboard/shots/{shot_id}", status_code=204)
async def delete_shot(
    project_id: str,
    shot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除镜头"""
    from sqlalchemy import select

    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Shot).where(Shot.id == shot_id, Shot.storyboard_id == storyboard.id)
    )
    shot = result.scalar_one_or_none()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    await db.delete(shot)
    await db.flush()
    return None


@router.post("/projects/{project_id}/storyboard/generate-from-script")
async def generate_storyboard_from_script(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从剧本场景一键生成分镜镜头（AI），替换已有镜头（受每日配额限制）

    两个关键语义：
      * 一个场景 = 一次 AI 调用 = 一份配额（旧实现 N 个场景只扣 1 份）；
      * **先全部生成成功，再替换旧镜头**（旧实现先删后调 AI，AI 失败会清空已有分镜）。
    """
    from sqlalchemy import select
    from app.models.script import Script, Scene

    storyboard = await _get_storyboard_or_create(project_id, current_user.id, db)

    # 读取剧本场景
    script_result = await db.execute(
        select(Script).where(Script.project_id == project_id)
    )
    script = script_result.scalar_one_or_none()
    scenes: List[Scene] = []
    if script:
        scene_result = await db.execute(
            select(Scene)
            .where(Scene.script_id == script.id)
            .order_by(Scene.sort_order)
        )
        scenes = list(scene_result.scalars().all())

    if not scenes:
        raise HTTPException(
            status_code=400,
            detail="剧本还没有场景，请先在剧本工坊创建场景后再生成分镜",
        )

    # 按场景数预占配额（每个场景一次 AI 调用）；中途超限则把已占用的全部退回
    reserved = 0
    try:
        for _ in range(len(scenes)):
            await acquire_ai_quota_or_429(db, current_user.id)
            reserved += 1
    except HTTPException:
        for _ in range(reserved):
            await refund_ai_quota_and_commit(db, current_user.id)
        raise

    # 逐场景生成（只写内存，不落库）；任一场景失败则整体回退
    planned: List[tuple] = []
    try:
        for scene in scenes:
            prompt = (
                f"场景 {scene.scene_number}：{scene.title}\n"
                f"地点：{scene.location}，时段：{scene.time_of_day}，"
                f"{'内景' if scene.interior else '外景'}\n"
                f"剧情概要：{scene.summary}\n"
                f"详细内容：{scene.content}"
            )
            shots = await ai_service.generate_storyboard(
                prompt, user_id=current_user.id, project_id=project_id
            )
            for s in shots:
                planned.append((scene, s))
    except AIUnavailableError as e:
        for _ in range(reserved):
            await refund_ai_quota_and_commit(db, current_user.id)
        raise HTTPException(status_code=503, detail=f"AI 分镜生成失败：{e}") from e

    # 全部成功后才替换旧镜头
    old_result = await db.execute(
        select(Shot).where(Shot.storyboard_id == storyboard.id)
    )
    for shot in old_result.scalars().all():
        await db.delete(shot)
    await db.flush()

    created = []
    for idx, (scene, s) in enumerate(planned, start=1):
        db.add(
            Shot(
                storyboard_id=storyboard.id,
                shot_number=idx,
                label=s["label"],
                description=s["description"],
                duration=s["duration"],
                camera_angle=s["camera_angle"],
                transition=s["transition"],
                scene_ref=scene.title,
                character_refs=[],
                sort_order=idx - 1,
            )
        )
        created.append(
            {
                "scene": scene.title,
                "label": s["label"],
                "description": s["description"],
                "duration": s["duration"],
                "camera_angle": s["camera_angle"],
                "transition": s["transition"],
            }
        )

    await db.flush()
    return {"status": "success", "total": len(created), "shots": created}


@router.get("/projects/{project_id}/storyboard/export")
async def export_storyboard(
    project_id: str,
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出分镜镜头（json）"""
    from fastapi.responses import Response
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Shot)
        .join(Storyboard, Storyboard.id == Shot.storyboard_id)
        .where(Storyboard.project_id == project_id)
        .order_by(Shot.sort_order)
    )
    shots = result.scalars().all()

    if (format or "json").lower() != "json":
        raise HTTPException(status_code=400, detail="仅支持 json 格式")

    data = {
        "project_id": project_id,
        "total": len(shots),
        "shots": [
            {
                "shot_number": s.shot_number,
                "label": s.label,
                "description": s.description,
                "duration": s.duration,
                "camera_angle": s.camera_angle,
                "transition": s.transition,
                "scene_ref": s.scene_ref,
                "character_refs": s.character_refs or [],
                "video_url": s.video_url or "",
                "image_url": s.image_url or "",
                "video_prompt": s.video_prompt or "",
            }
            for s in shots
        ],
    }
    import json as _json

    return Response(
        content=_json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="storyboard_{project_id[:8]}.json"'
        },
    )
