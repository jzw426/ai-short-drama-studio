"""进程内登录限流（M1 第一刀）。

为什么先做进程内：当前部署允许 Redis 不可用（/health 里 redis=unavailable 是常态），
引入 Redis 依赖会让"能不能登录"取决于另一个服务。所以先给单进程兜底：

- 键 = 客户端 IP + 用户名，连续失败 LOGIN_MAX_FAILURES 次 → 锁定 LOGIN_LOCKOUT_SECONDS 秒；
- 登录成功清零；
- 惰性清理过期条目，避免字典无界增长。

已知局限（写进交付文档，M2 处理）：多 worker / 多副本之间不共享计数，
重启清零；真正的分布式限流要在 M2 接 Redis 或网关层做。
"""
import threading
import time
from typing import Dict, Tuple


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
