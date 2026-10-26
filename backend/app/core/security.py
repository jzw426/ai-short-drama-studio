"""认证安全工具：密码哈希（PBKDF2-SHA256）与 JWT 签发/校验（PyJWT）"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 密码哈希，格式：iterations$salt$hash"""
    salt = secrets.token_hex(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return f"{iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码，使用常量时间比较防时序攻击"""
    try:
        iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


TOKEN_TTL_MINUTES = 60 * 24 * 7


def create_access_token(
    user_id: str,
    *,
    token_version: int = 0,
    expires_minutes: int = TOKEN_TTL_MINUTES,
) -> str:
    """签发 JWT，默认有效期 7 天。

    `ver` 是用户的会话代际：校验时与 users.token_version 比对，
    用户在别处登出/改密把它 +1，这张票立刻作废（无需黑名单表、无需清理过期项）。
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "ver": int(token_version or 0),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token_claims(token: str) -> Optional[dict]:
    """解析 JWT，返回完整 claim；无效或过期返回 None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str) -> Optional[str]:
    """解析 JWT，返回 user_id；无效或过期返回 None（不校验会话代际）"""
    claims = decode_token_claims(token)
    return claims.get("sub") if claims else None
