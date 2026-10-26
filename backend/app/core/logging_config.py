"""统一的日志配置。

背景：`settings.LOG_LEVEL` / `settings.LOG_FORMAT` 在此之前是**死配置**——
定义了、也写进了 .env.example，但全项目没有任何一处 logging 配置读取它们，
运行时日志全是 `print()`，既进不了采集（没有时间/级别/logger 名），
也无法按环境调整级别。生产排障时只能靠 print 的顺序猜。

用法：在进程入口（`app/main.py`、`app/tasks/celery_app.py`）各调用一次
`configure_logging()`，幂等。
"""

from __future__ import annotations

import json
import logging
import sys

from app.core.config import settings

_CONFIGURED = False

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """一行一个 JSON 对象，便于直接进日志采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 允许 logger.info("...", extra={"task_id": ...}) 携带结构化字段
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """按 settings 装配 root logger；重复调用只生效一次。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = (settings.LOG_LEVEL or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    if (settings.LOG_FORMAT or "").strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )

    root = logging.getLogger()
    # 移除已有 handler（uvicorn 之外通常没有；有则避免重复输出）
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # 第三方库降噪：httpx 每次请求一行 INFO 太吵
    logging.getLogger("httpx").setLevel(max(level, logging.WARNING))
    logging.getLogger("httpcore").setLevel(max(level, logging.WARNING))

    _CONFIGURED = True
