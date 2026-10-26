"""时间工具单元测试：utc_now 行为约定"""
from datetime import datetime, timedelta, timezone

from app.core.time_utils import utc_now


def test_utc_now_is_naive():
    assert utc_now().tzinfo is None


def test_utc_now_close_to_system_utc():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    now = utc_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    # 允许 ±2 秒误差
    assert before - now <= timedelta(seconds=2)
    assert now - after <= timedelta(seconds=2)


def test_utc_now_type():
    assert isinstance(utc_now(), datetime)
