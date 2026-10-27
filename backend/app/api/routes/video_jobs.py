"""AI 视频作业接口（M4-3）：提交 / 查询 / 取消。

提交只负责"落一条作业 + 入队"，真正的 provider 提交与轮询在
app.tasks.video_job_task 里一步步推进：接口立刻返回，用户不用盯着 5 分钟的
同步轮询，失败可以单独重试某个镜头，取消也能生效。
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.models.project import Project
from app.models.storyboard import Shot, Storyboard
from app.models.user import User
from app.models.video_job import AIVideoJob
from app.schemas.video_job import VideoJobCreate, VideoJobResponse
from app.tasks.video_job_task import enqueue_video_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["VideoJobs"])

# 可取消的状态：已是终态的作业再取消没有意义，直接 400 告诉调用方
_CANCELLABLE_STATUSES = ("pending", "submitted", "polling")


async def _job_response(job: AIVideoJob) -> VideoJobResponse:
    """统一出口：库里存规范 URL，响应时才签名（M1 媒体受控）。"""
    resp = VideoJobResponse.model_validate(job)
    # image_url 是入参（首帧图），保持库里的规范地址不回签，避免响应里给一个过期链接
    resp.video_url = await signed_media_url(job.video_url)
    return resp


async def _get_project_or_404(
    project_id: str, owner_id: str, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _get_shot_or_404(
    project_id: str, shot_id: str, db: AsyncSession
) -> Shot:
    """镜头必须存在于本项目（防越权：别人的镜头 id 不能拿来生成）"""
    result = await db.execute(
        select(Shot)
        .join(Storyboard, Storyboard.id == Shot.storyboard_id)
        .where(Storyboard.project_id == project_id, Shot.id == shot_id)
    )
    shot = result.scalar_one_or_none()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return shot


async def _get_owned_job_or_404(
    project_id: str, job_id: str, owner_id: str, db: AsyncSession
) -> AIVideoJob:
    result = await db.execute(
        select(AIVideoJob)
        .join(Project, Project.id == AIVideoJob.project_id)
        .where(
            AIVideoJob.id == job_id,
            AIVideoJob.project_id == project_id,
            Project.owner_id == owner_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="视频作业不存在")
    return job


@router.post(
    "/projects/{project_id}/shots/{shot_id}/video-jobs",
    response_model=VideoJobResponse,
    status_code=201,
)
async def submit_video_job(
    project_id: str,
    shot_id: str,
    data: VideoJobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为镜头提交一条 AI 视频生成作业（异步，立即返回）。"""
    await _get_project_or_404(project_id, current_user.id, db)
    shot = await _get_shot_or_404(project_id, shot_id, db)

    # 提示词优先级：请求体 > 镜头的 AI 优化提示词 > 画面描述
    prompt = (
        (data.prompt or "").strip()
        or (shot.video_prompt or "").strip()
        or (shot.description or "").strip()
    )
    if not prompt:
        raise HTTPException(
            status_code=400, detail="镜头没有可用的提示词，请在请求里提供 prompt"
        )
    # 首帧图同理：请求体 > 镜头已绑定的首帧图（图生视频是"镜头第一帧不崩"的关键）
    image_url = (
        (data.image_url or "").strip() or (shot.image_url or "").strip() or None
    )

    job = AIVideoJob(
        project_id=project_id,
        shot_id=shot.id,
        prompt=prompt[:4000],
        image_url=image_url,
        status="pending",
        duration=data.duration,
        poll_count=0,
        warnings="",
    )
    db.add(job)
    # 入队前必须先提交：worker 可能比事务更早拿到消息，那时还查不到这行
    # （M3-1 实测过的竞态：任务永远停在 pending）
    await db.commit()
    await db.refresh(job)

    try:
        # broker 不可达时 delay() 会长时间重试，必须加超时，别把接口挂死
        await asyncio.wait_for(
            asyncio.to_thread(enqueue_video_job, str(job.id)),
            timeout=settings.CELERY_SUBMIT_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 - 入队失败只标作业失败，不返 500
        logger.warning("[AIVideoJob] 入队失败，作业标记为失败: %s", e)
        job.status = "failed"
        job.error = f"任务队列不可用，提交失败: {e}"[:1024]
        await db.commit()

    await db.refresh(job)
    return await _job_response(job)


@router.get(
    "/projects/{project_id}/video-jobs", response_model=List[VideoJobResponse]
)
async def list_video_jobs(
    project_id: str,
    status: Optional[str] = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """项目的视频作业列表（新的在前；默认 50 条，最多 200 条）。"""
    await _get_project_or_404(project_id, current_user.id, db)

    filters = [AIVideoJob.project_id == project_id]
    if status:
        filters.append(AIVideoJob.status == status)
    result = await db.execute(
        select(AIVideoJob)
        .where(*filters)
        .order_by(AIVideoJob.created_at.desc())
        .limit(limit)
    )
    return [await _job_response(job) for job in result.scalars().all()]


@router.get(
    "/projects/{project_id}/video-jobs/{job_id}", response_model=VideoJobResponse
)
async def get_video_job(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询单条视频作业（前端按它轮询进度）。"""
    job = await _get_owned_job_or_404(project_id, job_id, current_user.id, db)
    return await _job_response(job)


@router.post(
    "/projects/{project_id}/video-jobs/{job_id}/cancel",
    response_model=VideoJobResponse,
)
async def cancel_video_job(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消作业。

    取消是**协作式**的：模型表里没有 celery_task_id 列（不归我改），拿不到真实
    task id，所以先落 cancelled 状态；worker 每次推进都会先读库，看到终态直接
    跳过，最多晚 POLL_INTERVAL_SECONDS 秒生效。如果将来补了 task id 列，这里的
    revoke 会自动生效，且 broker 不可达也绝不返 500。
    """
    job = await _get_owned_job_or_404(project_id, job_id, current_user.id, db)
    if job.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"作业当前状态为 {job.status}，无法取消"
        )

    job.status = "cancelled"
    job.error = None
    await db.commit()
    await db.refresh(job)

    celery_task_id = getattr(job, "celery_task_id", None)
    if celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.control.revoke(celery_task_id, terminate=False)
        except Exception as e:  # noqa: BLE001 - 取消已落库，revoke 失败只记日志
            logger.warning("[AIVideoJob] revoke 失败（已置 cancelled）: %s", e)

    return await _job_response(job)
