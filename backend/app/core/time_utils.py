"""时间工具：统一的 UTC 时间生成

项目约定：数据库存 naive UTC（SQLite 无时区类型）。
用 timezone-aware 计算后剥离 tzinfo，等价于旧 datetime.utcnow()，
但不触发 Python 3.12+ 的弃用警告，且语义更明确。
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """返回当前 UTC 时间（naive，兼容 SQLite 存储约定）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
