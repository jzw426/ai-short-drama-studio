from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import get_login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

# httpOnly 会话 Cookie 名称（前端经 withCredentials 自动携带）
COOKIE_NAME = "ai_drama_token"
TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 天，与 JWT 有效期一致

# 登录失败限流：同一 (客户端 IP, 用户名) 连续失败超过阈值即锁定一段时间。
# M1 第二刀起由 get_login_limiter() 选择后端：Redis（多 worker 共享）优先，
# 不可达时自动降级进程内；降级只打告警，不让登录整体不可用。


def _login_key(request: Request, username: str) -> str:
    """限流键：客户端 IP + 归一化用户名。

    注意：`request.client.host` 取的是直连对端地址。若后面挂反向代理，
    必须在可信代理层用 X-Forwarded-For 覆盖，否则所有用户会被算成同一个 IP。
    """
    host = request.client.host if request.client else "unknown"
    return f"{host}|{username.strip().lower()}"


def _set_auth_cookie(response: Response, token: str) -> None:
    """下发 httpOnly 会话 Cookie（XSS 无法读取；前端以 Cookie 为主通道）"""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=TOKEN_MAX_AGE,
        path="/",
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    data: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """注册新用户并直接返回 Token（同时下发 httpOnly Cookie）"""
    result = await db.execute(
        select(User).where(
            or_(User.username == data.username, User.email == data.email)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名或邮箱已被注册")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name or data.username,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # 上面的查重是 check-then-insert，并发注册会同时通过检查；靠唯一约束兜底
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名或邮箱已被注册")
    await db.refresh(user)

    token = create_access_token(user.id, token_version=user.token_version or 0)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """用户名密码登录，返回 Token（同时下发 httpOnly Cookie）

    连续失败超过阈值即锁定（429 + Retry-After），防止在线暴力破解。
    """
    key = _login_key(request, data.username)
    limiter = await get_login_limiter()
    try:
        retry_after = await limiter.retry_after(key)
    except Exception as exc:  # 限流后端故障不应连坐登录
        print(f"[WARNING] 限流后端读取失败，本次跳过限流: {exc}")
        retry_after = 0
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {retry_after} 秒后再试",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        try:
            await limiter.record_failure(key)
        except Exception as exc:  # 记不上就记不上，不能因此 500
            print(f"[WARNING] 限流后端写入失败: {exc}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    try:
        await limiter.reset(key)
    except Exception as exc:
        print(f"[WARNING] 限流后端重置失败: {exc}")
    token = create_access_token(user.id, token_version=user.token_version or 0)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """退出登录：清除 Cookie **并作废已签发的 Token**。

    M1 第一刀之前 logout 只删 Cookie，Bearer Token 在 7 天有效期内仍可用
    （抓到票的人照旧能访问）。现在把 users.token_version +1，服务端校验
    会话代际，旧票立刻失效。
    语义变化：登出 = 该账号全部设备下线（本项目单人多端场景，宁可多踢）。
    """
    current_user.token_version = (current_user.token_version or 0) + 1
    await db.flush()
    response.delete_cookie(COOKIE_NAME, path="/")
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user
