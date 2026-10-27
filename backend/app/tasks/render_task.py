"""Celery 渲染任务。

M1 第二刀重点修三处（原实现每一条都真实发生）：

- **取消不生效**：`cancel_requested` 由接口置位，worker 在每个可中断点检查。
  原实现只 revoke，AI 生成照跑、钱照烧，结束后还会把状态覆盖回 processing/completed。
- **重试等于重新烧钱**：`checkpoint` 保存已生成片段 URL，重试时复用；
  原实现 retry 从 Step 1 整段重来，最多 3 倍 AI 成本。
- **状态互踩**：进度回调无条件写 `status="processing"`，会把已取消/已完成的任务改回去。
"""
import asyncio
import logging
from typing import Optional

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.metrics import metrics
from app.core.time_utils import utc_now
from app.models.asset import RenderTask
from app.services.ai_service import AIUnavailableError
from app.services.render_service import RenderCancelled, render_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# error_message 是 Text，但没有必要把整个 traceback 塞给前端；保留足够诊断的长度。
MAX_ERROR_CHARS = 4000

# 创建 Celery worker 专用的数据库引擎（兼容 SQLite 和 PostgreSQL）。
#
# 这里必须用 NullPool：worker 每个任务走一次 asyncio.run()，即每次都是新的
# 事件循环，而连接池是进程级的。池化连接会带着上一个循环的 asyncpg Protocol，
# 第二个任务一查库就抛：
#   RuntimeError: Task ... got Future ... attached to a different loop
# 现场表现是第一个渲染任务成功、后续任务永远停在 queued（M3-1 容器全栈实测）。
celery_engine = create_async_engine(settings.DATABASE_URL, echo=False, poolclass=NullPool)
celery_async_session = async_sessionmaker(
    celery_engine, class_=AsyncSession, expire_on_commit=False
)

MAX_ATTEMPTS = 3  # 1 次执行 + 2 次重试

# ==================== 失败分类（M3-4） ====================
# 落 RenderTask.error_category，供 /ops/render-stats 聚合与告警。
# 分类只依据异常类型/错误文本，不改变 error_message 的内容与长度。
ERROR_CATEGORIES = (
    "ai_unavailable",
    "ffmpeg",
    "storage",
    "timeout",
    "cancelled",
    "other",
)

# 错误文本里的特征词（全部小写比较，中英文都覆盖）
_AI_HINTS = (
    "aiunavailableerror",
    "ai provider",
    "ai 服务",
    "provider 均不可用",
    "ai 调用",
    "文本 ai",
    "视频生成失败",
)
_AI_GENERIC_HINTS = (
    "没有任何镜头产出",
    "未生成任何",
    "没有可渲染的镜头",
)
_TIMEOUT_HINTS = ("timeout", "timed out", "超时", "deadline exceeded")
_FFMPEG_HINTS = ("ffmpeg", "ffprobe", "avframe", "invalid data found", "conversion failed")
_STORAGE_HINTS = (
    "storage",
    "minio",
    "s3",
    "bucket",
    "oss",
    "upload",
    "上传",
    "no space left",
    "disk full",
    "磁盘",
)
_CANCEL_HINTS = ("用户取消", "cancel")


def _contains_any(text: str, hints) -> bool:
    return any(h in text for h in hints)


def classify_render_error(
    error: Optional[BaseException] = None,
    message: Optional[str] = None,
    *,
    cancelled: bool = False,
) -> str:
    """把一次渲染失败归到 error_category 之一。

    - error：捕获到的异常（可为 None，此时只看 message）
    - message：已落库/待落库的 error_message 文本
    - cancelled：调用方已判定为取消（协作式取消的优先信号）

    返回值为 ERROR_CATEGORIES 之一；无法判断时返回 "other"。
    """
    if cancelled or isinstance(error, RenderCancelled):
        return "cancelled"

    text = f"{message or ''} {error or ''}".strip().lower()
    if not text and error is None:
        return "other"

    if _contains_any(text, _CANCEL_HINTS):
        return "cancelled"
    if isinstance(error, AIUnavailableError):
        return "ai_unavailable"
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if _contains_any(text, _FFMPEG_HINTS):
        return "ffmpeg"
    if _contains_any(text, _STORAGE_HINTS):
        return "storage"
    if _contains_any(text, _AI_HINTS):
        return "ai_unavailable"
    if _contains_any(text, _TIMEOUT_HINTS):
        return "timeout"
    if _contains_any(text, _AI_GENERIC_HINTS):
        return "ai_unavailable"
    return "other"


async def _load_task(task_id: str):
    async with celery_async_session() as session:
        return (
            await session.execute(select(RenderTask).where(RenderTask.id == task_id))
        ).scalar_one_or_none()


async def _is_cancelled(task_id: str) -> bool:
    """协作式取消检查点。每次查库，代价可忽略（相对一次 AI 视频生成）。"""
    async with celery_async_session() as session:
        flag = (
            await session.execute(
                select(RenderTask.cancel_requested).where(RenderTask.id == task_id)
            )
        ).scalar_one_or_none()
        return bool(flag)


async def _update_task_progress(task_id: str, progress: float, message: str) -> None:
    """更新进度。已取消/已完成的任务不再被"processing"覆盖。"""
    async with celery_async_session() as session:
        task = (
            await session.execute(select(RenderTask).where(RenderTask.id == task_id))
        ).scalar_one_or_none()
        if not task:
            return
        if task.status in ("cancelled", "completed", "failed"):
            return
        if task.cancel_requested:
            return
        task.progress = progress
        task.status = "processing"
        if not task.start_time:
            task.start_time = utc_now()
        await session.commit()


async def _set_task_result(
    task_id: str,
    status: str,
    output_url: str = "",
    subtitle_url: str = "",
    error: str = "",
    error_category: str = "",
) -> None:
    """写最终状态。取消是终态：除 "cancelled" 外任何结果都不许把它复活。"""
    async with celery_async_session() as session:
        task = (
            await session.execute(select(RenderTask).where(RenderTask.id == task_id))
        ).scalar_one_or_none()
        if not task:
            return
        if task.status == "cancelled" and status != "cancelled":
            return
        task.status = status
        task.end_time = utc_now()
        if task.start_time:
            task.duration = (task.end_time - task.start_time).total_seconds()
        if output_url:
            task.output_url = output_url
            task.progress = 100.0
        if subtitle_url:
            task.subtitle_url = subtitle_url
        if error:
            task.error_message = error[:MAX_ERROR_CHARS]
        if error_category:
            task.error_category = error_category[:20]
        await session.commit()


async def _save_checkpoint(task_id: str, data: dict) -> None:
    """落盘断点：已生成片段的 URL 清单。重试时据此跳过 AI 生成。"""
    async with celery_async_session() as session:
        task = (
            await session.execute(select(RenderTask).where(RenderTask.id == task_id))
        ).scalar_one_or_none()
        if not task:
            return
        task.checkpoint = data
        await session.commit()


async def _bump_attempt(task_id: str) -> int:
    async with celery_async_session() as session:
        task = (
            await session.execute(select(RenderTask).where(RenderTask.id == task_id))
        ).scalar_one_or_none()
        if not task:
            return MAX_ATTEMPTS + 1
        task.attempt = int(task.attempt or 0) + 1
        attempts = task.attempt
        await session.commit()
        return attempts


@shared_task(bind=True, max_retries=MAX_ATTEMPTS - 1)
def execute_render(self, task_id: str):
    """Celery 异步渲染任务（同步 worker 内跑异步逻辑）。"""

    async def _run():
        task = await _load_task(task_id)
        if not task:
            # 入队消息理论上在事务提交之后才发出（render.py 先 commit 再 delay），
            # 但历史消息或极端时序仍可能查不到行。这里退避重试几次，
            # 而不是直接 return 把任务永久留在 queued。
            retries = int(getattr(self.request, "retries", 0) or 0)
            max_retries = int(self.max_retries or 0)
            if retries < max_retries:
                logger.warning(
                    "[Render Task] Task %s not found, retry %s/%s in 2s",
                    task_id,
                    retries + 1,
                    max_retries,
                )
                raise self.retry(countdown=2)
            logger.error("[Render Task] Task %s not found after retries", task_id)
            return
        if task.status == "cancelled" or task.cancel_requested:
            await _set_task_result(
                task_id, "cancelled", error="用户取消", error_category="cancelled"
            )
            metrics.record_render_failure("cancelled")
            return

        project_id = str(task.project_id)
        config = dict(task.config or {})
        resume = dict(task.checkpoint or {})

        async def progress_callback(progress: float, message: str):
            # 进度以数据库为准（前端读的是 RenderTask.progress）。
            # update_state 只是给 Flower / AsyncResult 看的附加信息：result backend
            # 抖动（Redis 重启、eager 模式无 backend）绝不能把一次正在烧钱的
            # 渲染打断——旧代码在这里抛 ConnectionError，任务会被整体判失败。
            await _update_task_progress(task_id, progress, message)
            if getattr(self.request, "is_eager", False):
                return
            try:
                self.update_state(
                    state="PROGRESS", meta={"progress": progress, "message": message}
                )
            except Exception as exc:  # noqa: BLE001 - 仅日志，不影响渲染
                logger.debug("[Render Task] update_state 失败（忽略）: %s", exc)

        async def checkpoint_cb(data: dict):
            await _save_checkpoint(task_id, data)

        try:
            results = await render_service.execute_render(
                task_id=task_id,
                project_id=project_id,
                config=config,
                progress_callback=progress_callback,
                cancel_check=lambda: _is_cancelled(task_id),
                checkpoint_cb=checkpoint_cb,
                resume=resume,
            )
        except RenderCancelled:
            await _set_task_result(
                task_id, "cancelled", error="用户取消", error_category="cancelled"
            )
            metrics.record_render_failure("cancelled")
            return
        except Exception as exc:
            attempts = await _bump_attempt(task_id)
            if attempts >= MAX_ATTEMPTS:
                category = classify_render_error(exc)
                await _set_task_result(
                    task_id,
                    "failed",
                    error=f"重试 {MAX_ATTEMPTS} 次仍失败: {exc}",
                    error_category=category,
                )
                metrics.record_render_failure(category)
                return
            logger.warning(
                "[Render Task] 第 %s 次失败，60s 后重试（复用断点）: %s", attempts, exc
            )
            raise self.retry(exc=exc, countdown=60)

        for warning in results.get("warnings") or []:
            logger.info("[Render Task] %s warning: %s", task_id, warning)

        if results.get("output_url"):
            await _set_task_result(
                task_id,
                "completed",
                output_url=results["output_url"],
                subtitle_url=results.get("subtitle_url") or "",
            )
        else:
            errors = list(results.get("errors") or [])
            if not errors:
                errors = ["渲染失败，未生成输出文件（详见 worker 日志）"]
            message = "; ".join(errors)
            category = classify_render_error(None, message=message)
            await _set_task_result(
                task_id, "failed", error=message, error_category=category
            )
            metrics.record_render_failure(category)

    asyncio.run(_run())


def enqueue_render_task(task_id: str):
    """路由层入队入口：显式绑定 celery_app。

    与 enqueue_video_job 同因：路由在 asyncio.to_thread 里调用，子线程里 Celery
    的 current_app 是默认 app，没有 broker_transport_options —— filesystem broker
    下会去找相对路径 data_in/ 并抛 WinError 3。
    """
    return celery_app.send_task(
        "app.tasks.render_task.execute_render", args=[str(task_id)]
    )
