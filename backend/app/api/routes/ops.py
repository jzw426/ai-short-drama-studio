"""运维端点：指标快照 + 增强健康检查 + AI 调度清单 + 用量/渲染统计（P3/P4/M3-4）。"""
import os
import shutil
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.core.config import settings
from app.core.database import engine, get_db
from app.core.deps import get_current_user
from app.core.metrics import metrics
from app.core.time_utils import utc_now
from app.models.ai_usage import AIUsageEvent
from app.models.asset import RenderTask
from app.services.ai_service import AI_OPERATIONS, ai_service

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
        # MinIO 模式：探测桶可用（ensure_bucket 幂等）。原来这里只回显配置值
        # "minio"，公开 /health 的归纳逻辑会把它当成 error，监控必然误报。
        try:
            from app.services.storage_service import storage_service

            await storage_service.ensure_bucket()
            checks["storage"] = "ok"
        except Exception as e:
            checks["storage"] = f"error: {e}"
            checks["status"] = "degraded"

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


# ==================== 用量 / 渲染统计（M3-4，需登录） ====================

_USAGE_DAYS_MAX = 90


def _window_start(days: int) -> datetime:
    """最近 days 天（含今天）的起点：UTC 当天 00:00 往前推 days-1 天。"""
    start = utc_now() - timedelta(days=days - 1)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _empty_bucket() -> dict:
    return {
        "calls": 0,
        "success": 0,
        "failure": 0,
        "timeout": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "tokens": 0,
        "estimated_cost_usd": 0.0,
        "duration_ms_sum": 0,
        "duration_ms_count": 0,
    }


def _finalize_bucket(bucket: dict) -> dict:
    calls = bucket["calls"]
    result = {
        "calls": calls,
        "success": bucket["success"],
        "failure": bucket["failure"],
        "timeout": bucket["timeout"],
        "prompt_tokens": bucket["prompt_tokens"],
        "completion_tokens": bucket["completion_tokens"],
        "tokens": bucket["tokens"],
        "estimated_cost_usd": round(bucket["estimated_cost_usd"], 6),
        "avg_duration_ms": (
            round(bucket["duration_ms_sum"] / bucket["duration_ms_count"], 1)
            if bucket["duration_ms_count"]
            else 0.0
        ),
    }
    return result


@router.get("/ops/usage")
async def usage_stats(
    days: int = Query(7, ge=1, le=_USAGE_DAYS_MAX, description="统计最近 N 天（含今天）"),
    operation: Optional[str] = Query(
        None, description="按 operation 过滤：script/character/storyboard/video"
    ),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """AI 调用用量与成本（需登录）。

    返回最近 N 天的按日聚合（calls/success/failure/tokens/estimated_cost_usd）
    以及窗口合计 total；数据源为 ai_usage_events 明细表。

    成本是**估算值**：单价见 app/core/usage_pricing.py，默认值待商务确认。
    """
    if operation is not None and operation not in AI_OPERATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"operation 必须是 {list(AI_OPERATIONS)} 之一",
        )

    start = _window_start(days)
    today = utc_now().date()
    start_date = start.date()

    stmt = (
        select(
            AIUsageEvent.created_at,
            AIUsageEvent.status,
            AIUsageEvent.prompt_tokens,
            AIUsageEvent.completion_tokens,
            AIUsageEvent.estimated_cost_usd,
            AIUsageEvent.duration_ms,
        )
        .where(AIUsageEvent.created_at >= start)
        .order_by(AIUsageEvent.created_at)
    )
    if operation:
        stmt = stmt.where(AIUsageEvent.operation == operation)
    rows = (await db.execute(stmt)).all()

    daily = {}
    for offset in range(days):
        day = (start_date + timedelta(days=offset)).isoformat()
        daily[day] = _empty_bucket()

    total = _empty_bucket()
    for created_at, status, prompt_tokens, completion_tokens, cost, duration_ms in rows:
        day = (created_at or utc_now()).date().isoformat()
        bucket = daily.get(day)
        if bucket is None:  # 跨时区/时钟漂移的游离行，归入今天，避免丢数
            bucket = daily.setdefault(today.isoformat(), _empty_bucket())
        for target in (bucket, total):
            target["calls"] += 1
            target["prompt_tokens"] += int(prompt_tokens or 0)
            target["completion_tokens"] += int(completion_tokens or 0)
            target["tokens"] += int(prompt_tokens or 0) + int(completion_tokens or 0)
            target["estimated_cost_usd"] += float(cost or 0.0)
            if duration_ms:
                target["duration_ms_sum"] += int(duration_ms)
                target["duration_ms_count"] += 1
        if status == "success":
            bucket["success"] += 1
            total["success"] += 1
        elif status == "timeout":
            bucket["timeout"] += 1
            total["timeout"] += 1
        else:
            bucket["failure"] += 1
            total["failure"] += 1

    total_view = _finalize_bucket(total)
    total_view["success_rate"] = (
        round(total["success"] / total["calls"], 4) if total["calls"] else 0.0
    )

    return {
        "days": days,
        "operation": operation,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "daily": [
            {"date": day, **_finalize_bucket(bucket)} for day, bucket in daily.items()
        ],
        "total": total_view,
    }


@router.get("/ops/render-stats")
async def render_stats(
    days: int = Query(7, ge=1, le=_USAGE_DAYS_MAX, description="统计最近 N 天（含今天）"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """渲染任务统计（需登录）：总数/成功率/平均耗时/失败分类分布。

    统计窗口按 RenderTask.created_at 计算；成功率 = 完成 / (完成 + 失败)，
    排队中/处理中的任务不计入分母（尚未有结果）。
    """
    start = _window_start(days)
    today = utc_now().date()

    stmt = (
        select(
            RenderTask.status,
            RenderTask.duration,
            RenderTask.error_category,
        )
        .where(RenderTask.created_at >= start)
        .order_by(RenderTask.created_at)
    )
    rows = (await db.execute(stmt)).all()

    status_counts: Counter = Counter()
    durations = []
    categories: Counter = Counter()
    for status, duration, category in rows:
        status_counts[status] += 1
        if status == "completed" and duration is not None:
            durations.append(float(duration))
        elif status == "failed":
            categories[(category or "other")[:20]] += 1

    completed = status_counts.get("completed", 0)
    failed = status_counts.get("failed", 0)
    finished = completed + failed
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    return {
        "days": days,
        "start_date": start.date().isoformat(),
        "end_date": today.isoformat(),
        "total": len(rows),
        "completed": completed,
        "failed": failed,
        "cancelled": status_counts.get("cancelled", 0),
        "running": status_counts.get("queued", 0) + status_counts.get("processing", 0),
        "success_rate": round(completed / finished, 4) if finished else 0.0,
        "avg_duration_seconds": round(avg_duration, 2),
        "failure_categories": [
            {"category": category, "count": count}
            for category, count in sorted(
                categories.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "by_status": dict(status_counts),
    }
