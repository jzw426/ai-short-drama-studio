"""AI 用量配额（P3）：每用户每日 AI 调用上限，超限返回 429。

设计（M1 修正，替代原来的 check-then-act）：
  * 日界统一用 **UTC 日期**（`utc_now().date()`），与库内其它时间戳一致；
    原先用 `date.today()` 是本地时区，跨时区/跨凌晨会算错日。
  * 采用 **先占后用、失败退回**：
        ticket = await reserve_ai_quota(db, user.id)   # 原子自增，超限抛 QuotaExceeded
        try:
            ... 调用 AI ...
        except AIUnavailableError:
            await refund_ai_quota(db, user.id)          # AI 失败不扣用户配额
            raise
    自增语句带 `WHERE count < limit` 条件，靠数据库行锁/条件更新保证并发下不会超发，
    不再依赖"先读后写"。
  * **不在请求中途 commit**：事务边界交给 `get_db`（请求结束统一提交/回滚），
    否则一次请求里多次 commit 会让"扣了配额但业务失败"无法回滚。
"""
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import utc_now
from app.models.ai_usage import AIUsage


class QuotaExceeded(Exception):
    """当日 AI 配额已用尽。"""

    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
        super().__init__(f"AI quota exceeded: {used}/{limit}")


def _current_day() -> str:
    """配额按 UTC 自然日切分，与库内其它时间戳口径一致。"""
    return utc_now().astimezone(timezone.utc).date().isoformat()


async def _ensure_row(db: AsyncSession, user_id: str, day: str) -> None:
    """保证 (user_id, day) 行存在；并发插入由唯一约束兜住，不抛给调用方。"""
    existing = await db.execute(
        select(AIUsage.id).where(AIUsage.user_id == user_id, AIUsage.date == day)
    )
    if existing.scalar_one_or_none() is not None:
        return
    savepoint = await db.begin_nested()
    try:
        db.add(AIUsage(user_id=user_id, date=day, count=0))
        await db.flush()
        await savepoint.commit()
    except IntegrityError:
        # 另一个请求抢先建了行：回滚保存点即可，随后继续走原子自增
        await savepoint.rollback()


async def get_ai_usage(db: AsyncSession, user_id: str) -> int:
    """当前 UTC 日已用次数。"""
    result = await db.execute(
        select(AIUsage.count).where(
            AIUsage.user_id == user_id, AIUsage.date == _current_day()
        )
    )
    return int(result.scalar_one_or_none() or 0)


async def check_ai_quota(db: AsyncSession, user_id: str) -> tuple[bool, int, int]:
    """只读预检。返回 (是否可用, 当前已用, 每日上限)。

    仅用于在真正干活前快速返回 429；**不能**作为并发下的正确性保证，
    正确性由 `reserve_ai_quota` 的条件自增保证。
    """
    limit = settings.AI_DAILY_QUOTA
    if limit <= 0:  # 0/负数视为不限额
        return True, 0, limit
    used = await get_ai_usage(db, user_id)
    return used < limit, used, limit


async def reserve_ai_quota(db: AsyncSession, user_id: str) -> int:
    """原子占用一次配额，返回占用后的当日已用次数；超限抛 QuotaExceeded。"""
    limit = settings.AI_DAILY_QUOTA
    if limit <= 0:
        return 0
    day = _current_day()
    await _ensure_row(db, user_id, day)

    result = await db.execute(
        update(AIUsage)
        .where(
            AIUsage.user_id == user_id,
            AIUsage.date == day,
            AIUsage.count < limit,
        )
        .values(count=AIUsage.count + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        used = await get_ai_usage(db, user_id)
        raise QuotaExceeded(used=used, limit=limit)
    return await get_ai_usage(db, user_id)


async def refund_ai_quota(db: AsyncSession, user_id: str) -> None:
    """退回一次配额（AI 调用失败时使用，避免让用户为失败买单）。"""
    if settings.AI_DAILY_QUOTA <= 0:
        return
    day = _current_day()
    await db.execute(
        update(AIUsage)
        .where(AIUsage.user_id == user_id, AIUsage.date == day, AIUsage.count > 0)
        .values(count=AIUsage.count - 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )


def _retry_after_seconds() -> int:
    """距离下一个 UTC 零点的秒数，用作 429 的 Retry-After。"""
    now = utc_now().astimezone(timezone.utc)
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((next_midnight - now).total_seconds()))


async def acquire_ai_quota_or_429(db: AsyncSession, user_id: str) -> None:
    """原子占用一次配额；超限直接抛 HTTP 429（带 Retry-After）。"""
    try:
        await reserve_ai_quota(db, user_id)
    except QuotaExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=f"今日 AI 调用已达上限（{e.limit} 次），请明天再试",
            headers={"Retry-After": str(_retry_after_seconds())},
        ) from e


# 兼容旧调用名：consume == reserve（旧代码在 AI 成功后才调用；新代码请用 acquire/refund）
async def consume_ai_quota(db: AsyncSession, user_id: str) -> int:
    return await reserve_ai_quota(db, user_id)
