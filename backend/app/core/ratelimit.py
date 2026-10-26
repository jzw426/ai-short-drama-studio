"""进程内登录限流（M1 第一刀）。

为什么先做进程内：当前部署允许 Redis 不可用（/health 里 redis=unavailable 是常态），
引入 Redis 依赖会让"能不能登录"取决于另一个服务。所以先给单进程兜底：

- 键 = 客户端 IP + 用户名，连续失败 LOGIN_MAX_FAILURES 次 → 锁定 LOGIN_LOCKOUT_SECONDS 秒；
- 登录成功清零；
- 惰性清理过期条目，避免字典无界增长。

M1 第二刀：`get_login_limiter()` 优先用 Redis（多 worker 共享计数，这才是
真正防撞库的形态），Redis 不可达时自动降级到进程内实现——限流不该成为登录的
单点故障。降级会打印告警，运维应关注 /health 的 redis 状态。

局限仍在：RedisFailureLimiter 用 INCR+EXPIRE 做固定窗口，跨窗口边界可放大到
2 倍阈值；要严格滑动窗口需 Lua 或 ZSET，留到网关层统一做。
"""
import threading
import time
from typing import Dict, Optional, Tuple


class FailureLimiter:
    def __init__(self, max_failures: int, lockout_seconds: int) -> None:
        self.max_failures = max(1, int(max_failures))
        self.lockout_seconds = max(1, int(lockout_seconds))
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[int, float]] = {}  # key -> (失败次数, 解锁时间)

    def _prune(self, now: float) -> None:
        if len(self._entries) < 1024:
            return
        for key in [k for k, (_, until) in self._entries.items() if until and until <= now]:
            self._entries.pop(key, None)

    def retry_after(self, key: str) -> int:
        """返回还需等待的秒数；0 表示当前允许尝试。"""
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return 0
            _, locked_until = entry
            if locked_until and locked_until > now:
                return int(locked_until - now) + 1
            if locked_until and locked_until <= now:
                self._entries.pop(key, None)
            return 0

    def record_failure(self, key: str) -> int:
        """记一次失败；返回锁定剩余秒数（0 表示还没触发锁定）。"""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            failures = self._entries.get(key, (0, 0.0))[0] + 1
            locked_until = 0.0
            if failures >= self.max_failures:
                locked_until = now + self.lockout_seconds
            self._entries[key] = (failures, locked_until)
            return int(locked_until - now) + 1 if locked_until else 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

# ===== 异步后端（M1 第二刀）=====


class AsyncLimiterProtocol:
    """异步限流接口。登录路由只认这个协议，不关心背后是 Redis 还是内存。"""

    async def retry_after(self, key: str) -> int:  # pragma: no cover - 协议
        raise NotImplementedError

    async def record_failure(self, key: str) -> int:  # pragma: no cover
        raise NotImplementedError

    async def reset(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError


class AsyncMemoryLimiter(AsyncLimiterProtocol):
    """把进程内 FailureLimiter 包成异步接口（不引入事件循环锁的开销）。"""

    def __init__(self, inner: FailureLimiter) -> None:
        self._inner = inner

    async def retry_after(self, key: str) -> int:
        return self._inner.retry_after(key)

    async def record_failure(self, key: str) -> int:
        return self._inner.record_failure(key)

    async def reset(self, key: str) -> None:
        self._inner.reset(key)


class RedisFailureLimiter(AsyncLimiterProtocol):
    """Redis 计数 + 过期锁。多 worker / 多副本共享，重启不清零。

    key 上存失败次数，每次失败刷新 TTL（滑动锁窗口）；次数达阈值即锁定到 TTL 结束。
    客户端需支持 async 接口（redis.asyncio 或测试用 fake）。
    """

    PREFIX = "ai_drama:login_fail:"

    def __init__(self, client, max_failures: int, lockout_seconds: int, prefix: str = PREFIX) -> None:
        self._client = client
        self.max_failures = max(1, int(max_failures))
        self.lockout_seconds = max(1, int(lockout_seconds))
        self.prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def retry_after(self, key: str) -> int:
        k = self._k(key)
        count = int(await self._client.get(k) or 0)
        if count < self.max_failures:
            return 0
        ttl = int(await self._client.ttl(k) or 0)
        return ttl if ttl > 0 else 0

    async def record_failure(self, key: str) -> int:
        k = self._k(key)
        count = int(await self._client.incr(k))
        await self._client.expire(k, self.lockout_seconds)
        return self.lockout_seconds if count >= self.max_failures else 0

    async def reset(self, key: str) -> None:
        await self._client.delete(self._k(key))


_login_limiter: "Optional[AsyncLimiterProtocol]" = None


async def get_login_limiter() -> AsyncLimiterProtocol:
    """按配置选择限流后端：auto/redis → Redis（可达时），否则进程内。"""
    global _login_limiter
    if _login_limiter is not None:
        return _login_limiter

    from app.core.config import settings

    backend = (settings.RATE_LIMIT_BACKEND or "auto").strip().lower()
    use_redis = backend in ("redis", "auto") and (settings.REDIS_URL or "").startswith("redis")

    if use_redis:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            await client.ping()
            _login_limiter = RedisFailureLimiter(
                client,
                max_failures=settings.LOGIN_MAX_FAILURES,
                lockout_seconds=settings.LOGIN_LOCKOUT_SECONDS,
            )
            print("[Ratelimit] 登录限流后端 = Redis（跨进程共享）")
            return _login_limiter
        except Exception as exc:  # noqa: BLE001 - 降级路径必须兜住所有异常
            if backend == "redis":
                raise
            print(
                f"[WARNING] Redis 限流不可用（{exc}），降级为进程内限流："
                "多 worker 下各算各的，防撞库强度下降"
            )

    _login_limiter = AsyncMemoryLimiter(
        FailureLimiter(
            max_failures=settings.LOGIN_MAX_FAILURES,
            lockout_seconds=settings.LOGIN_LOCKOUT_SECONDS,
        )
    )
    return _login_limiter


def reset_login_limiter_cache() -> None:
    """测试用：丢弃已选定的后端，下次调用重新探测。"""
    global _login_limiter
    _login_limiter = None
