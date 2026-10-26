import os
import tempfile

from celery import Celery

from app.core.config import settings
from app.core.logging_config import configure_logging

configure_logging()

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
    # 自己装配日志（JSON/plain 由 settings 决定），不让 Celery 覆盖 root logger
    worker_hijack_root_logger=False,
)


def _configure_filesystem_broker() -> None:
    """filesystem:// 传输：本机无 Redis 时也能跑**真实 worker 进程**。

    只用于开发/验收（compose 里仍是 Redis）。producer 与 worker 必须指向
    同一个目录，默认落在系统临时目录，可用 CELERY_FILESYSTEM_DIR 覆盖。
    """
    data_dir = settings.CELERY_FILESYSTEM_DIR or os.path.join(
        tempfile.gettempdir(), "ai-drama-celery"
    )
    folders = {name: os.path.join(data_dir, name) for name in ("in", "out", "processed")}
    for path in folders.values():
        os.makedirs(path, exist_ok=True)
    celery_app.conf.broker_transport_options = {
        "data_folder_in": folders["in"],
        "data_folder_out": folders["in"],
        "data_folder_processed": folders["processed"],
        "polling_interval": 0.2,
    }


if (settings.CELERY_BROKER_URL or "").startswith("filesystem://"):
    _configure_filesystem_broker()

celery_app.autodiscover_tasks(["app.tasks"])
