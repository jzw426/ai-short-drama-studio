"""登录限流的 Redis 后端单元测试（用 fake client，不依赖真实 Redis）。"""
import pytest

from app.core.ratelimit import RedisFailureLimiter


class FakeRedis:
    """只实现 limiter 用到的五个命令，语义与 redis-py 保持一致。"""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        self.ttls[key] = int(seconds)
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1 if existed else 0


@pytest.fixture
def limiter():
    return RedisFailureLimiter(FakeRedis(), max_failures=3, lockout_seconds=300)


@pytest.mark.asyncio
async def test_below_threshold_is_not_locked(limiter):
    assert await limiter.retry_after("k") == 0
    assert await limiter.record_failure("k") == 0
    assert await limiter.record_failure("k") == 0
    assert await limiter.retry_after("k") == 0


@pytest.mark.asyncio
async def test_threshold_locks_and_reports_ttl(limiter):
    for _ in range(3):
        await limiter.record_failure("k")
    assert await limiter.retry_after("k") == 300


@pytest.mark.asyncio
async def test_reset_clears_counter(limiter):
    for _ in range(3):
        await limiter.record_failure("k")
    await limiter.reset("k")
    assert await limiter.retry_after("k") == 0
    assert limiter._client.store == {}


@pytest.mark.asyncio
async def test_keys_are_isolated_and_prefixed(limiter):
    for _ in range(3):
        await limiter.record_failure("a")
    assert await limiter.retry_after("b") == 0
    assert "ai_drama:login_fail:a" in limiter._client.store
