"""认证依赖：从 Authorization Bearer Token 或 httpOnly Cookie 解析当前用户"""
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Optional

from app.core.database import get_db
from app.core.security import decode_token_claims
from app.models.user import User

# 与 auth.py 保持一致
COOKIE_NAME = "ai_drama_token"


async def _resolve_user(
    authorization: str, request: Optional[Request], db: AsyncSession
) -> Optional[User]:
    """Bearer 优先，其次 httpOnly Cookie；解析失败返回 None（不抛错）。"""
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif request is not None:
        token = request.cookies.get(COOKIE_NAME, "") or ""

    if not token:
        return None
    claims = decode_token_claims(token)
    if not claims:
        return None
    user_id = claims.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    # 会话代际校验：用户登出/改密后旧票立即失效（比黑名单省一张表、无需清理）
    if int(claims.get("ver", 0) or 0) != int(user.token_version or 0):
        return None
    return user


async def get_current_user(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> User:
    """校验凭证（Bearer 优先，其次 httpOnly Cookie），返回当前用户；无效则 401"""
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif request is not None:
        token = request.cookies.get(COOKIE_NAME, "") or ""

    if not token:
        raise HTTPException(status_code=401, detail="未登录或凭证缺失")

    user = await _resolve_user(authorization, request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期或凭证无效，请重新登录")

    # 供请求日志/指标中间件记录当前用户
    if request is not None:
        request.state.auth_user = {"id": user.id, "username": user.username}
    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """可选的当前用户：用于既能匿名访问、又要区分身份的端点（如媒体、登录限流）。"""
    return await _resolve_user(request.headers.get("authorization", ""), request, db)
