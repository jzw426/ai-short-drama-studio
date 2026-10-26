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
async def get_metrics():
    """进程内运行指标（公开聚合数据，无敏感信息）"""
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


@router.get("/health")
async def health_check():
    """增强健康检查：服务 + 数据库 + 存储 + Redis（可选）"""
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

    # Redis 可选探测（不可达不降级，仅提示）
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1.5)
        await r.ping()
        checks["redis"] = "ok"
        await r.aclose()
    except Exception as e:
        checks["redis"] = f"unavailable: {e}"

    checks["uptime_seconds"] = metrics.snapshot()["uptime_seconds"]
    return checks
