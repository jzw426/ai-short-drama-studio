"""媒体访问签名（M1）。

背景：T0 前 /uploads 是 StaticFiles 公开挂载，任何拿到 URL 的人都能下载
全部素材与成片（已在尽调中实测 200）。M1 改成"受控媒体端点"后，
URL 必须显式授权才能访问。授权有两种：

1. 签名 URL：`/uploads/<object_name>?exp=<unix>&sig=<hmac>`
   用于 <img>/<video>/下载链接这类无法携带 Authorization 的场景；
2. 已登录用户（Bearer 或 httpOnly Cookie）+ 该项目 owner 校验。

存储里保存的始终是规范 URL（`/uploads/<project_id>/<uuid>.<ext>`），
签名只在响应阶段生成 —— 否则每次读取都要回写数据库，且链接一旦泄露永久有效。
"""
import hashlib
import hmac
import time
from typing import Optional

from app.core.config import settings

_UPLOADS_PREFIX = "/uploads/"
_SIG_LEN = 32


def object_name_from_url(url: Optional[str]) -> Optional[str]:
    """从规范/签名 URL 中取出 object_name；Not our /uploads URL 时返回 None。"""
    if not url:
        return None
    clean = url.split("?", 1)[0].split("#", 1)[0]
    if _UPLOADS_PREFIX in clean:
        return clean.split(_UPLOADS_PREFIX, 1)[-1].lstrip("/") or None
    return None


def media_signature(object_name: str, exp: int) -> str:
    msg = f"{object_name}:{int(exp)}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()[:_SIG_LEN]


def verify_media_signature(
    object_name: str, exp: Optional[int], sig: Optional[str]
) -> bool:
    """校验签名与过期时间；任何一项缺失/不符都返回 False。"""
    if not object_name or exp is None or not sig:
        return False
    if not settings.SECRET_KEY:
        return False
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_int < int(time.time()):
        return False
    return hmac.compare_digest(media_signature(object_name, exp_int), sig)


async def signed_media_url(
    url: Optional[str], ttl: Optional[int] = None
) -> Optional[str]:
    """把存储 URL 转成浏览器可直接用的受控链接（异步版本，路由层统一用它）。

    - local：追加 `?exp=&sig=`（HMAC，纯本地计算，无 IO）；
    - minio：换成**预签名 URL**（SigV4；桶已私有，裸 URL 现在会 403）；
    - 外链（第三方图床等）：原样返回。

    为什么必须异步：minio-py 是同步 SDK（预签名是纯本地 SigV4 计算，但调用方
    仍要把它丢进 asyncio.to_thread，避免将来 SDK 行为变化时阻塞事件循环）。
    """
    if not url:
        return None
    if settings.STORAGE_TYPE == "local" or object_name_from_url(url):
        return sign_media_url(url, ttl)
    from app.services.storage_service import storage_service

    return await storage_service.presigned_url_for(url, ttl)


def sign_media_url(url: Optional[str], ttl: Optional[int] = None) -> Optional[str]:
    """把规范 URL 签名；外链（MinIO 预签名、第三方图床）原样返回。"""
    if not url:
        return None
    object_name = object_name_from_url(url)
    if not object_name:
        return url
    expires = int(time.time()) + int(
        settings.MEDIA_URL_TTL_SECONDS if ttl is None else ttl
    )
    return (
        f"{_UPLOADS_PREFIX}{object_name}"
        f"?exp={expires}&sig={media_signature(object_name, expires)}"
    )
