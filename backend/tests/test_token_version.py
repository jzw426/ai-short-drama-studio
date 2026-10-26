"""会话代际（token_version）单元测试：登出 / 改密后旧 Token 立即失效。

为什么不是黑名单：黑名单要存"每个未过期 Token"的 id，容量随登录次数线性增长；
代际只需在用户行上 +1，旧 Token 全部自动作废，且天然多 worker 一致（读库）。
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.deps import _resolve_user
from app.core.security import create_access_token, decode_token_claims
from app.models.user import User


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _add_user(session, *, token_version=0, is_active=True):
    user = User(
        id="u-1",
        username="alice",
        email="alice@example.com",
        password_hash="x",
        token_version=token_version,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    return user


def test_claims_carry_version():
    claims = decode_token_claims(create_access_token("u-1", token_version=7))
    assert claims is not None
    assert claims["sub"] == "u-1"
    assert claims["ver"] == 7


def test_claims_default_version_is_zero():
    claims = decode_token_claims(create_access_token("u-1"))
    assert claims["ver"] == 0


@pytest.mark.asyncio
async def test_token_accepted_when_versions_match(session):
    await _add_user(session, token_version=2)
    token = create_access_token("u-1", token_version=2)
    user = await _resolve_user(f"Bearer {token}", None, session)
    assert user is not None and user.id == "u-1"


@pytest.mark.asyncio
async def test_stale_token_rejected_after_logout(session):
    user = await _add_user(session, token_version=0)
    stale = create_access_token("u-1", token_version=0)

    # 模拟 logout：代际 +1
    user.token_version = 1
    await session.commit()

    assert await _resolve_user(f"Bearer {stale}", None, session) is None


@pytest.mark.asyncio
async def test_inactive_user_rejected(session):
    await _add_user(session, is_active=False)
    token = create_access_token("u-1", token_version=0)
    assert await _resolve_user(f"Bearer {token}", None, session) is None


@pytest.mark.asyncio
async def test_garbage_token_rejected(session):
    await _add_user(session)
    assert await _resolve_user("Bearer not-a-jwt", None, session) is None
    assert await _resolve_user("", None, session) is None
