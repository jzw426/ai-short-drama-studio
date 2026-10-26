"""AI 用量配额（P3）：每用户每日 AI 调用上限，超限返回 429。

用法（在 AI 生成类端点内）：
    allowed, used, limit = await check_ai_quota(db, user.id)
    if not allowed:
        raise HTTPException(429, f"今日 AI 调用已达上限（{limit} 次），请明天再试")
    ... 调用 AI 服务 ...
    await consume_ai_quota(db, user.id)   # 成功后才计数
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_usage import AIUsage


async def _get_or_create(db: AsyncSession, user_id: str, day: str) -> AIUsage:
    result = await db.execute(
        select(AIUsage).where(AIUsage.user_id == user_id, AIUsage.date == day)
    )
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = AIUsage(user_id=user_id, date=day, count=0)
        db.add(usage)
    return usage


async def check_ai_quota(db: AsyncSession, user_id: str) -> tuple[bool, int, int]:
    """检查配额是否可用。返回 (是否可用, 当前已用次数, 每日上限)。"""
    if settings.AI_DAILY_QUOTA <= 0:  # 0/负数视为不限额
        return True, 0, settings.AI_DAILY_QUOTA
    usage = await _get_or_create(db, user_id, date.today().isoformat())
    return usage.count < settings.AI_DAILY_QUOTA, usage.count, settings.AI_DAILY_QUOTA


async def consume_ai_quota(db: AsyncSession, user_id: str) -> int:
    """消耗一次配额并提交，返回当日累计次数。"""
    usage = await _get_or_create(db, user_id, date.today().isoformat())
    usage.count += 1
    await db.commit()
    return usage.count
