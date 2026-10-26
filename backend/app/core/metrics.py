"""进程内指标收集器（单实例版，无需外部依赖）。

对外暴露：
- metrics.record(method, path, status_code, duration_ms, user_id=None)
- metrics.record_ai_call(operation, status)      # AI 调用计数（M3-4）
- metrics.record_render_failure(category)        # 渲染失败分类计数（M3-4）
- metrics.snapshot() -> dict  聚合快照

注意：这些都是**进程内**计数（worker 进程的计数不会出现在 API 进程的 /metrics 里），
与既有的请求指标口径一致。
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
        # AI 调用计数：{(operation, status): count}
        self._ai_calls: dict = defaultdict(int)
        # 渲染失败分类：{category: count}
        self._render_failures: dict = defaultdict(int)

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

    def record_ai_call(self, operation: str, status: str) -> None:
        """AI 调用计数（按 operation+status）。记账失败也要计数——观测优先于落库。"""
        with self._lock:
            self._ai_calls[(str(operation or "unknown"), str(status or "unknown"))] += 1

    def record_render_failure(self, category: str) -> None:
        """渲染失败分类计数（ai_unavailable/ffmpeg/storage/timeout/cancelled/other）。"""
        with self._lock:
            self._render_failures[str(category or "other")] += 1

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
            ai_calls = [
                {"operation": op, "status": st, "count": count}
                for (op, st), count in sorted(
                    self._ai_calls.items(), key=lambda kv: (-kv[1], kv[0])
                )
            ]
            render_failures = [
                {"category": category, "count": count}
                for category, count in sorted(
                    self._render_failures.items(), key=lambda kv: (-kv[1], kv[0])
                )
            ]
            return {
                "total_requests": self._total,
                "in_flight": self._in_flight,
                "errors_5xx": self._errors,
                "errors_4xx": self._client_errors,
                "avg_duration_ms": avg_ms,
                "uptime_seconds": uptime,
                "by_status": dict(self._by_status),
                "top_paths": top_paths,
                "ai_calls_total": ai_calls,
                "render_failures_total": render_failures,
            }


metrics = Metrics()
