"""登录失败限流单元测试。"""
from app.core.ratelimit import FailureLimiter


def test_locks_after_max_failures():
    limiter = FailureLimiter(max_failures=3, lockout_seconds=60)
    key = "127.0.0.1|alice"
    assert limiter.retry_after(key) == 0
    assert limiter.record_failure(key) == 0
    assert limiter.record_failure(key) == 0
    assert limiter.record_failure(key) > 0
    locked = limiter.retry_after(key)
    assert 0 < locked <= 61


def test_reset_clears_counter():
    limiter = FailureLimiter(max_failures=2, lockout_seconds=60)
    key = "127.0.0.1|bob"
    limiter.record_failure(key)
    limiter.reset(key)
    assert limiter.retry_after(key) == 0
    assert limiter.record_failure(key) == 0


def test_keys_are_isolated():
    limiter = FailureLimiter(max_failures=1, lockout_seconds=60)
    limiter.record_failure("ip|alice")
    assert limiter.retry_after("ip|alice") > 0
    assert limiter.retry_after("ip|bob") == 0
