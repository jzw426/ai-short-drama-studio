from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.storyboard import Storyboard, Shot
from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota_and_commit
from app.services.ai_service import AIUnavailableError, ai_service
from app.models.project import Project
from app.models.user import User
from app.schemas.storyboard import (
    StoryboardUpdate, StoryboardResponse, ShotCreate, ShotUpdate, ShotResponse,
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

    return storyboard


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
    return result.scalar_one()


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
    return list(result.scalars().all())


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
        sort_order=data.sort_order,
    )
    db.add(shot)
    await db.flush()
    await db.refresh(shot)
    return shot


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
    return shot


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
