"""运维端点：指标快照 + 增强健康检查 + AI 调度清单（P3/P4）。"""
import os
import shutil

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.database import engine
from app.core.deps import get_current_user
from app.core.metrics import metrics
from app.services.ai_service import ai_service

router = APIRouter(tags=["Ops"])


@router.get("/metrics")
async def get_metrics(current_user=Depends(get_current_user)):
    """进程内运行指标。

    T0：需要登录。原实现完全公开，外部可据此测绘内部接口清单、流量与错误率，
    且 path 维度用原始 URL（含 UUID）做 key 会让字典无上限增长（M1 修复）。
    """
    return metrics.snapshot()


@router.get("/ai/providers")
async def ai_providers(current_user=Depends(get_current_user)):
    """AI 模型调度清单：当前按能力配置的 provider 链与运行状态（Key 已脱敏）。

    用途：查看当前实际调度哪些大模型的 API、各自模型名/端点/是否可用/是否冷却中。
    """
    status = ai_service.provider_status()
    return {
        "quota": {
            "daily_limit": settings.AI_DAILY_QUOTA,
            "cooldown_threshold": settings.AI_PROVIDER_FAILURE_THRESHOLD,
            "cooldown_seconds": settings.AI_PROVIDER_COOLDOWN_SECONDS,
        },
        "providers": status,
    }


async def _collect_checks() -> dict:
    """采集各组件的真实状态（含敏感细节，只给已登录调用方）。"""
    checks: dict = {"status": "healthy", "version": settings.APP_VERSION}

    # 数据库连通性
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"

    # 存储目录可用性（本地模式）
    if settings.STORAGE_TYPE == "local":
        try:
            path = os.path.abspath(settings.STORAGE_LOCAL_PATH)
            os.makedirs(path, exist_ok=True)
            usage = shutil.disk_usage(path)
            checks["storage"] = {
                "path": path,
                "free_bytes": usage.free,
                "free_gb": round(usage.free / (1024 ** 3), 2),
            }
        except Exception as e:
            checks["storage"] = f"error: {e}"
            checks["status"] = "degraded"
    else:
        checks["storage"] = settings.STORAGE_TYPE

    # Redis 可选探测（不可达不降级，仅提示）
    client = None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1.5)
        await client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"unavailable: {e}"
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    checks["uptime_seconds"] = metrics.snapshot()["uptime_seconds"]
    return checks


def _public_view(checks: dict) -> dict:
    """脱敏：只留状态枚举，不回显服务器绝对路径、剩余磁盘、异常原文。"""

    def summarize(value) -> str:
        if value == "ok":
            return "ok"
        if isinstance(value, str) and value.startswith("unavailable"):
            return "unavailable"
        return "error"

    components = {
        key: ("ok" if not isinstance(value, str) else summarize(value))
        for key, value in checks.items()
        if key not in {"status", "version", "uptime_seconds"}
    }
    return {
        "status": checks["status"],
        "version": checks["version"],
        "components": components,
        "uptime_seconds": checks.get("uptime_seconds"),
    }


@router.get("/health")
async def health_check():
    """公开存活探针：仅状态汇总（供 docker/负载均衡健康检查）。"""
    return _public_view(await _collect_checks())


@router.get("/health/details")
async def health_details(current_user=Depends(get_current_user)):
    """详细健康信息（需登录）：含路径、磁盘余量与异常原文。"""
    return await _collect_checks()
