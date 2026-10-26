"""配额原子扣减（先占后用、失败退回）单元测试。"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.quota import (
    QuotaExceeded,
    acquire_ai_quota_or_429,
    get_ai_usage,
    refund_ai_quota,
    reserve_ai_quota,
)
from app.models.ai_usage import AIUsage


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AIUsage.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_until_limit_then_block(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 2)
    assert await reserve_ai_quota(session, "u1") == 1
    assert await reserve_ai_quota(session, "u1") == 2
    with pytest.raises(QuotaExceeded):
        await reserve_ai_quota(session, "u1")
    assert await get_ai_usage(session, "u1") == 2
    await session.commit()


@pytest.mark.asyncio
async def test_refund_frees_a_slot(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 1)
    await reserve_ai_quota(session, "u2")
    with pytest.raises(QuotaExceeded):
        await reserve_ai_quota(session, "u2")
    await refund_ai_quota(session, "u2")
    assert await get_ai_usage(session, "u2") == 0
    assert await reserve_ai_quota(session, "u2") == 1
    await session.commit()


@pytest.mark.asyncio
async def test_users_are_isolated(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 1)
    await reserve_ai_quota(session, "u3")
    assert await get_ai_usage(session, "u4") == 0
    await session.commit()


@pytest.mark.asyncio
async def test_guard_raises_429_with_retry_after(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 1)
    await acquire_ai_quota_or_429(session, "u5")
    with pytest.raises(HTTPException) as exc:
        await acquire_ai_quota_or_429(session, "u5")
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    await session.commit()


@pytest.mark.asyncio
async def test_unlimited_when_quota_non_positive(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 0)
    for _ in range(5):
        await acquire_ai_quota_or_429(session, "u6")
    assert await get_ai_usage(session, "u6") == 0
    await session.commit()
