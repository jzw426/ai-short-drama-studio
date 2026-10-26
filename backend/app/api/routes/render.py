import asyncio
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.models.asset import RenderTask
from app.models.project import Project
from app.models.user import User
from app.schemas.asset import RenderSubmitRequest, RenderTaskResponse, RenderStatusResponse

router = APIRouter(tags=["Render"])

# 这些状态表示"任务已在跑且不该再排一次队"
_ACTIVE_STATUSES = ("queued", "processing", "completed")


async def _task_response(task: RenderTask) -> RenderTaskResponse:
    """统一出口：库里存规范 URL，响应时才签名（M1 媒体受控）。

    MinIO 私有桶模式下这里生成预签名 URL，所以必须是 async。
    """
    resp = RenderTaskResponse.model_validate(task)
    resp.output_url = await signed_media_url(resp.output_url)
    return resp


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
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交渲染任务（支持幂等键，重复提交不会重复扣 AI 费用）"""
    await _get_project_or_404(project_id, current_user.id, db)

    # 幂等：前端为一次点击生成一个 key，双击/重试/网络重发都落回同一个任务。
    # 原实现没有幂等，一次卡顿用户点三下就排三次队，AI 视频按次计费，直接三倍成本。
    if data.idempotency_key:
        existing = (
            await db.execute(
                select(RenderTask).where(
                    RenderTask.project_id == project_id,
                    RenderTask.idempotency_key == data.idempotency_key,
                    RenderTask.status.in_(_ACTIVE_STATUSES),
                )
            )
        ).scalars().first()
        if existing:
            response.status_code = 200
            return await _task_response(existing)

    render_task = RenderTask(
        project_id=project_id,
        name=data.name,
        status="queued",
        progress=0.0,
        config=data.config.model_dump(),
        idempotency_key=data.idempotency_key,
        attempt=0,
        checkpoint={},
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
    return await _task_response(render_task)


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
        output_url=await signed_media_url(task.output_url),
        error_message=task.error_message,
    )


@router.get("/projects/{project_id}/render/tasks", response_model=List[RenderTaskResponse])
async def list_render_tasks(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目的所有渲染任务"""
    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(RenderTask)
        .where(RenderTask.project_id == project_id)
        .order_by(RenderTask.created_at.desc())
    )
    return [await _task_response(t) for t in result.scalars().all()]


@router.post("/render/{task_id}/cancel", response_model=RenderStatusResponse)
async def cancel_render_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消渲染任务。

    先写协作式标志（worker 在每个可中断点读它并主动退出），再 revoke Celery。
    原实现只 revoke：正在跑的 AI 生成不会中断，钱继续烧，而且 worker 随后
    还会把状态改回 processing/completed。
    """
    task = await _get_owned_task_or_404(task_id, current_user.id, db)

    if task.status not in ("queued", "processing"):
        raise HTTPException(status_code=400, detail="只能取消排队中或处理中的任务")

    task.cancel_requested = True
    task.status = "cancelled"
    task.error_message = "用户取消"
    task.end_time = task.end_time or task.created_at
    await db.flush()

    if task.celery_task_id:
        try:
            from celery.result import AsyncResult

            AsyncResult(task.celery_task_id).revoke(terminate=True)
        except Exception as e:
            print(f"[WARNING] Celery revoke 失败（协作式标志仍会生效）: {e}")

    await db.refresh(task)

    return RenderStatusResponse(
        task_id=str(task.id),
        status=task.status,
        progress=task.progress,
        output_url=await signed_media_url(task.output_url),
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

    return {"download_url": await signed_media_url(task.output_url)}
