"""Celery 渲染任务。

M1 第二刀重点修三处（原实现每一条都真实发生）：

- **取消不生效**：`cancel_requested` 由接口置位，worker 在每个可中断点检查。
  原实现只 revoke，AI 生成照跑、钱照烧，结束后还会把状态覆盖回 processing/completed。
- **重试等于重新烧钱**：`checkpoint` 保存已生成片段 URL，重试时复用；
  原实现 retry 从 Step 1 整段重来，最多 3 倍 AI 成本。
- **状态互踩**：进度回调无条件写 `status="processing"`，会把已取消/已完成的任务改回去。
"""
import asyncio

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.time_utils import utc_now
from app.models.asset import RenderTask
from app.services.render_service import RenderCancelled, render_service

# 创建 Celery worker 专用的数据库引擎（兼容 SQLite 和 PostgreSQL）
_engine_kwargs = {"echo": False}
# PostgreSQL 才需要连接池参数，SQLite 不支持
if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({"pool_size": 5, "max_overflow": 5})

celery_engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
celery_async_session = async_sessionmaker(
    celery_engine, class_=AsyncSession, expire_on_commit=False
)

MAX_ATTEMPTS = 3  # 1 次执行 + 2 次重试


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
    task_id: str, status: str, output_url: str = "", error: str = ""
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
        if error:
            task.error_message = error
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
            print(f"[Render Task] Task {task_id} not found")
            return
        if task.status == "cancelled" or task.cancel_requested:
            await _set_task_result(task_id, "cancelled", error="用户取消")
            return

        project_id = str(task.project_id)
        config = dict(task.config or {})
        resume = dict(task.checkpoint or {})

        async def progress_callback(progress: float, message: str):
            await _update_task_progress(task_id, progress, message)
            self.update_state(state="PROGRESS", meta={"progress": progress, "message": message})

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
            await _set_task_result(task_id, "cancelled", error="用户取消")
            return
        except Exception as exc:
            attempts = await _bump_attempt(task_id)
            if attempts >= MAX_ATTEMPTS:
                await _set_task_result(
                    task_id,
                    "failed",
                    error=f"重试 {MAX_ATTEMPTS} 次仍失败: {exc}",
                )
                return
            print(f"[Render Task] 第 {attempts} 次失败，60s 后重试（复用断点）: {exc}")
            raise self.retry(exc=exc, countdown=60)

        if results.get("output_url"):
            await _set_task_result(task_id, "completed", output_url=results["output_url"])
        else:
            errors = results.get("errors", [])
            await _set_task_result(
                task_id,
                "failed",
                error="; ".join(errors) if errors else "渲染失败，未生成输出文件",
            )

    asyncio.run(_run())
