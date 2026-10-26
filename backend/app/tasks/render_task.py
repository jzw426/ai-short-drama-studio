import asyncio
from datetime import datetime
from app.core.time_utils import utc_now
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.asset import RenderTask
from app.services.render_service import render_service

# 创建 Celery worker 专用的数据库引擎（兼容 SQLite 和 PostgreSQL）
_engine_kwargs = {
    "echo": False,
}
# PostgreSQL 才需要连接池参数，SQLite 不支持
if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 5,
    })

celery_engine = create_async_engine(
    settings.DATABASE_URL,
    **_engine_kwargs,
)

celery_async_session = async_sessionmaker(
    celery_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _update_task_progress(task_id: str, progress: float, message: str):
    """更新渲染任务进度到数据库"""
    async with celery_async_session() as session:
        result = await session.execute(
            select(RenderTask).where(RenderTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.progress = progress
            task.status = "processing"
            if not task.start_time:
                task.start_time = utc_now()
            await session.commit()


async def _set_task_result(task_id: str, status: str, output_url: str = "", error: str = ""):
    """设置渲染任务最终结果"""
    async with celery_async_session() as session:
        result = await session.execute(
            select(RenderTask).where(RenderTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
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


@shared_task(bind=True, max_retries=2)
def execute_render(self, task_id: str):
    """
    Celery 异步渲染任务
    使用 asyncio.run 在同步 worker 中运行异步逻辑
    """

    async def _run():
        # 从数据库获取任务详情
        async with celery_async_session() as session:
            result = await session.execute(
                select(RenderTask).where(RenderTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if not task:
                print(f"[Render Task] Task {task_id} not found")
                return

            project_id = str(task.project_id)
            config = task.config

        # 进度回调
        async def progress_callback(progress: float, message: str):
            await _update_task_progress(task_id, progress, message)
            # 更新 Celery 任务状态
            self.update_state(
                state="PROGRESS",
                meta={
                    "progress": progress,
                    "message": message,
                },
            )

        # 执行渲染
        try:
            results = await render_service.execute_render(
                task_id=task_id,
                project_id=project_id,
                config=config,
                progress_callback=progress_callback,
            )

            if results.get("output_url"):
                await _set_task_result(
                    task_id,
                    "completed",
                    output_url=results["output_url"],
                )
            else:
                errors = results.get("errors", [])
                await _set_task_result(
                    task_id,
                    "failed",
                    error="; ".join(errors) if errors else "渲染失败，未生成输出文件",
                )
        except Exception as e:
            await _set_task_result(task_id, "failed", error=str(e))
            raise self.retry(exc=e, countdown=60)

    asyncio.run(_run())
