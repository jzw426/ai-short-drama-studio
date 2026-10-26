import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.asset import RenderTask
from app.models.project import Project
from app.models.user import User
from app.schemas.asset import RenderSubmitRequest, RenderTaskResponse, RenderStatusResponse

router = APIRouter(tags=["Render"])


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


async def _get_owned_task_or_404(
    task_id: str, owner_id: str, db: AsyncSession
) -> RenderTask:
    """按项目归属校验渲染任务"""
    from sqlalchemy import select

    result = await db.execute(
        select(RenderTask)
        .join(Project, Project.id == RenderTask.project_id)
        .where(RenderTask.id == task_id, Project.owner_id == owner_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="渲染任务不存在")
    return task


@router.post("/projects/{project_id}/render", response_model=RenderTaskResponse, status_code=201)
async def submit_render_task(
    project_id: str,
    data: RenderSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交渲染任务"""
    await _get_project_or_404(project_id, current_user.id, db)

    # 创建渲染任务记录
    render_task = RenderTask(
        project_id=project_id,
        name=data.name,
        status="queued",
        progress=0.0,
        config=data.config.model_dump(),
    )
    db.add(render_task)
    await db.flush()

    # 提交 Celery 异步任务，并保存真实 celery task id 供取消使用
    # 注意：broker 不可达时 delay() 可能长时间重试，必须加超时保护，避免接口被挂死
    try:
        from app.tasks.render_task import execute_render
        celery_result = await asyncio.wait_for(
            asyncio.to_thread(execute_render.delay, str(render_task.id)),
            timeout=settings.CELERY_SUBMIT_TIMEOUT,
        )
        render_task.celery_task_id = str(celery_result.id)
    except Exception as e:
        print(f"[WARNING] Celery 任务提交失败，渲染任务标记为失败: {e}")
        render_task.status = "failed"
        render_task.error_message = f"任务队列不可用，提交失败: {e}"

    await db.flush()
    await db.refresh(render_task)
    return render_task


@router.get("/render/{task_id}/status", response_model=RenderStatusResponse)
async def get_render_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询渲染任务状态"""
    task = await _get_owned_task_or_404(task_id, current_user.id, db)

    return RenderStatusResponse(
        task_id=str(task.id),
        status=task.status,
        progress=task.progress,
        output_url=task.output_url,
        error_message=task.error_message,
    )


@router.get("/projects/{project_id}/render/tasks", response_model=List[RenderTaskResponse])
async def list_render_tasks(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目的所有渲染任务"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(RenderTask)
        .where(RenderTask.project_id == project_id)
        .order_by(RenderTask.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/render/{task_id}/cancel", response_model=RenderStatusResponse)
async def cancel_render_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消渲染任务"""
    from celery.result import AsyncResult

    task = await _get_owned_task_or_404(task_id, current_user.id, db)

    if task.status not in ("queued", "processing"):
        raise HTTPException(status_code=400, detail="只能取消排队中或处理中的任务")

    # 取消 Celery 任务（使用真实 celery task id，而非数据库记录 ID）
    if task.celery_task_id:
        try:
            AsyncResult(task.celery_task_id).revoke(terminate=True)
        except Exception as e:
            print(f"[WARNING] Celery 取消失败: {e}")

    task.status = "failed"
    task.error_message = "用户取消"
    await db.flush()
    await db.refresh(task)

    return RenderStatusResponse(
        task_id=str(task.id),
        status=task.status,
        progress=task.progress,
        output_url=task.output_url,
        error_message=task.error_message,
    )


@router.get("/render/{task_id}/download")
async def get_download_url(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取渲染结果下载地址"""
    task = await _get_owned_task_or_404(task_id, current_user.id, db)

    if task.status != "completed":
        raise HTTPException(status_code=400, detail="渲染任务尚未完成")

    if not task.output_url:
        raise HTTPException(status_code=404, detail="输出文件不存在")

    return {"download_url": task.output_url}
