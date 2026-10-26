"""结构化请求日志 + 指标采集中间件。"""
import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.metrics import metrics


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每个请求：方法/路径/状态码/耗时/用户，并写入进程内指标。"""

    async def dispatch(self, request: Request, call_next):
        # 排除指标/健康等运维端点，避免自刷计数
        path = request.url.path
        if path.startswith("/api/v1/metrics") or path.startswith("/api/v1/health"):
            return await call_next(request)

        metrics.begin()
        start = time.perf_counter()
        user_id = None
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            # 尽力从请求状态取当前用户（认证后由 deps 注入）
            try:
                auth_state = request.state.auth_user
                if auth_state:
                    user_id = auth_state.get("id") or auth_state.get("sub")
            except Exception:
                user_id = None

            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            status = getattr(response, "status_code", 500)
            metrics.record(request.method, path, status, duration_ms, user_id)

            log_entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "level": "INFO",
                "logger": "http",
                "method": request.method,
                "path": path,
                "status": status,
                "duration_ms": duration_ms,
                "user": user_id,
                "client": request.client.host if request.client else "",
            }
            print(json.dumps(log_entry, ensure_ascii=False))
