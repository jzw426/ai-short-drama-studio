"""安全模块单元测试：密码哈希与 JWT"""
import pytest

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


def test_hash_password_roundtrip():
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)


def test_hash_password_wrong():
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


def test_hash_salts_are_unique():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_access_token_expired():
    token = create_access_token("user-123", expires_minutes=-1)
    assert decode_access_token(token) is None


def test_access_token_tampered():
    token = create_access_token("user-123")
    assert decode_access_token(token + "x") is None
