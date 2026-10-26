from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "ai_short_drama_studio",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.render_task"],
)

# Celery 配置
celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 渲染任务超时 1 小时
    task_soft_time_limit=3300,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    result_expires=86400,  # 结果保留 24 小时
    # broker 连接保护：不可达时快速失败，避免任务提交/发布长时间挂起
    broker_connection_timeout=4,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=3,
)

celery_app.autodiscover_tasks(["app.tasks"])
