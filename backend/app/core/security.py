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


def create_access_token(user_id: str, expires_minutes: int = 60 * 24 * 7) -> str:
    """签发 JWT，默认有效期 7 天"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> Optional[str]:
    """解析 JWT，返回 user_id；无效或过期返回 None"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
