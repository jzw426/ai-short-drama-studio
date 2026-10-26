from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.script import Script, Scene, AIPromptHistory
from app.models.project import Project
from app.models.user import User
from app.schemas.script import (
    ScriptUpdate, ScriptResponse, SceneCreate, SceneUpdate, SceneResponse,
    AIGenerateRequest, AIGenerateResponse,
)
from app.services.ai_service import ai_service
from app.core.quota import check_ai_quota, consume_ai_quota

router = APIRouter(tags=["Scripts"])


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


async def _get_script_or_create(
    project_id: str, owner_id: str, db: AsyncSession
) -> Script:
    from sqlalchemy import select

    result = await db.execute(
        select(Script).where(Script.project_id == project_id)
    )
    script = result.scalar_one_or_none()
    if not script:
        project = await _get_project_or_404(project_id, owner_id, db)
        script = Script(
            project_id=project_id,
            title=f"{project.title} - 剧本",
        )
        db.add(script)
        await db.flush()
        await db.refresh(script)
    return script


@router.get("/projects/{project_id}/script", response_model=ScriptResponse)
async def get_script(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目剧本"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Script)
        .where(Script.project_id == project_id)
        .options(
            selectinload(Script.scenes),
            selectinload(Script.ai_prompts),
        )
    )
    script = result.scalar_one_or_none()
    if not script:
        script = await _get_script_or_create(project_id, current_user.id, db)
        # 重新查询以加载关联
        result = await db.execute(
            select(Script)
            .where(Script.project_id == project_id)
            .options(
                selectinload(Script.scenes),
                selectinload(Script.ai_prompts),
            )
        )
        script = result.scalar_one()

    return script


@router.put("/projects/{project_id}/script", response_model=ScriptResponse)
async def update_script(
    project_id: str,
    data: ScriptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新剧本内容"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    script = await _get_script_or_create(project_id, current_user.id, db)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(script, key, value)

    await db.flush()

    result = await db.execute(
        select(Script)
        .where(Script.id == script.id)
        .options(selectinload(Script.scenes), selectinload(Script.ai_prompts))
    )
    return result.scalar_one()


@router.post("/projects/{project_id}/script/ai-generate", response_model=AIGenerateResponse)
async def ai_generate_script(
    project_id: str,
    request: AIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 辅助生成剧本内容（受每日配额限制）"""
    allowed, used, limit = await check_ai_quota(db, current_user.id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"今日 AI 调用已达上限（{limit} 次），请明天再试",
        )
    script = await _get_script_or_create(project_id, current_user.id, db)

    existing_context = script.content[-2000:] if script.content else ""
    generated = await ai_service.generate_script(
        prompt=request.prompt,
        context=existing_context,
    )

    # 记录历史
    history = AIPromptHistory(
        script_id=script.id,
        prompt=request.prompt,
        response=generated,
    )
    db.add(history)

    # 追加到剧本
    if script.content:
        script.content += "\n\n" + generated
    else:
        script.content = generated
    script.word_count = len(script.content)

    await db.flush()
    await consume_ai_quota(db, current_user.id)

    return AIGenerateResponse(
        generated_content=generated,
        prompt=request.prompt,
    )


# ===== 场景管理 =====

@router.get("/projects/{project_id}/script/scenes", response_model=List[SceneResponse])
async def list_scenes(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取剧本所有场景"""
    from sqlalchemy import select

    script = await _get_script_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Scene)
        .where(Scene.script_id == script.id)
        .order_by(Scene.sort_order)
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/script/scenes", response_model=SceneResponse, status_code=201)
async def create_scene(
    project_id: str,
    data: SceneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新场景"""
    script = await _get_script_or_create(project_id, current_user.id, db)

    scene = Scene(
        script_id=script.id,
        scene_number=data.scene_number,
        title=data.title,
        location=data.location,
        time_of_day=data.time_of_day,
        interior=data.interior,
        summary=data.summary,
        content=data.content,
        duration=data.duration,
        sort_order=data.sort_order,
    )
    db.add(scene)
    await db.flush()
    await db.refresh(scene)
    return scene


@router.put("/projects/{project_id}/script/scenes/{scene_id}", response_model=SceneResponse)
async def update_scene(
    project_id: str,
    scene_id: str,
    data: SceneUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新场景"""
    from sqlalchemy import select

    script = await _get_script_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Scene).where(Scene.id == scene_id, Scene.script_id == script.id)
    )
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(scene, key, value)

    await db.flush()
    await db.refresh(scene)
    return scene


@router.delete("/projects/{project_id}/script/scenes/{scene_id}", status_code=204)
async def delete_scene(
    project_id: str,
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除场景"""
    from sqlalchemy import select

    script = await _get_script_or_create(project_id, current_user.id, db)
    result = await db.execute(
        select(Scene).where(Scene.id == scene_id, Scene.script_id == script.id)
    )
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    await db.delete(scene)
    await db.flush()
    return None


@router.get("/projects/{project_id}/script/export")
async def export_script(
    project_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出剧本（markdown / txt）"""
    from fastapi.responses import Response
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Script)
        .where(Script.project_id == project_id)
        .options(selectinload(Script.scenes))
    )
    script = result.scalar_one_or_none()
    if not script:
        script = await _get_script_or_create(project_id, current_user.id, db)
        result = await db.execute(
            select(Script)
            .where(Script.id == script.id)
            .options(selectinload(Script.scenes))
        )
        script = result.scalar_one()

    scenes = list(script.scenes)
    fmt = (format or "markdown").lower()
    if fmt not in ("markdown", "txt"):
        raise HTTPException(status_code=400, detail="仅支持 markdown / txt 格式")

    lines = []
    heading = lambda s: (f"# {s}" if fmt == "markdown" else s)
    sub = lambda s: (f"## {s}" if fmt == "markdown" else s)
    bullet = lambda s: (f"- {s}" if fmt == "markdown" else f"- {s}")

    lines.append(heading(script.title or "剧本"))
    lines.append("")

    if scenes:
        for scene in scenes:
            lines.append(sub(f"场景 {scene.scene_number}：{scene.title}"))
            lines.append(bullet(f"地点：{scene.location}"))
            lines.append(bullet(f"时段：{scene.time_of_day}"))
            lines.append(bullet(f"{'内景' if scene.interior else '外景'}"))
            if scene.duration:
                lines.append(bullet(f"时长：{scene.duration} 秒"))
            if scene.summary:
                lines.append("")
                lines.append(scene.summary)
            if scene.content:
                lines.append("")
                lines.append(scene.content)
            lines.append("")
    elif script.content:
        lines.append(script.content)
    else:
        lines.append("（剧本为空）")

    content = "\n".join(lines)
    ext = "md" if fmt == "markdown" else "txt"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="script_{project_id[:8]}.{ext}"'
        },
    )
