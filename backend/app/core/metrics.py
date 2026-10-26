"""进程内指标收集器（单实例版，无需外部依赖）。

对外暴露：
- metrics.record(method, path, status_code, duration_ms, user_id=None)
- metrics.snapshot() -> dict  聚合快照
"""
import threading
import time
from collections import defaultdict
from typing import Optional


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._total = 0
        self._errors = 0          # 5xx
        self._client_errors = 0   # 4xx
        self._duration_ms_sum = 0.0
        self._by_path: dict = defaultdict(lambda: {"count": 0, "errors": 0, "duration_ms_sum": 0.0})
        self._by_status: dict = defaultdict(int)
        self._in_flight = 0

    def begin(self):
        with self._lock:
            self._in_flight += 1

    def record(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user_id: Optional[str] = None,
    ):
        with self._lock:
            self._total += 1
            self._in_flight = max(0, self._in_flight - 1)
            self._duration_ms_sum += duration_ms
            if status_code >= 500:
                self._errors += 1
            elif status_code >= 400:
                self._client_errors += 1

            route = f"{method} {path}"
            p = self._by_path[route]
            p["count"] += 1
            p["duration_ms_sum"] += duration_ms
            if status_code >= 500:
                p["errors"] += 1

            self._by_status[str(status_code)] += 1

    def snapshot(self) -> dict:
        with self._lock:
            uptime = round(time.time() - self._started_at, 2)
            avg_ms = round(self._duration_ms_sum / self._total, 2) if self._total else 0.0
            top_paths = sorted(
                (
                    {
                        "route": route,
                        "count": v["count"],
                        "errors": v["errors"],
                        "avg_ms": round(v["duration_ms_sum"] / v["count"], 2) if v["count"] else 0.0,
                    }
                    for route, v in self._by_path.items()
                ),
                key=lambda x: x["count"],
                reverse=True,
            )[:20]
            return {
                "total_requests": self._total,
                "in_flight": self._in_flight,
                "errors_5xx": self._errors,
                "errors_4xx": self._client_errors,
                "avg_duration_ms": avg_ms,
                "uptime_seconds": uptime,
                "by_status": dict(self._by_status),
                "top_paths": top_paths,
            }


metrics = Metrics()
