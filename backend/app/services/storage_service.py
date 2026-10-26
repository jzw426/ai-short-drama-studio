import asyncio
import io
import os
from typing import Optional

from app.core.config import settings


def _storage_root() -> str:
    return os.path.abspath(settings.STORAGE_LOCAL_PATH)


def _secure_local_path(object_name: str) -> str:
    """把 object_name 解析到存储根之内；越界（../、绝对路径、跨盘）直接抛错。

    T0 修复：旧实现直接 os.path.join(root, object_name)，配合上传接口里
    客户端可控的 filename，可用 "proj/uuid_../../../evil.png" 写到 uploads 之外。
    """
    if not object_name or object_name.strip() in {".", ".."}:
        raise ValueError(f"非法的存储对象名: {object_name!r}")
    if object_name.startswith(("/", "\\")) or ":" in object_name:
        raise ValueError(f"非法的存储对象名（绝对路径）: {object_name!r}")
    root = _storage_root()
    normalized = object_name.replace("\\", "/")
    candidate = os.path.abspath(os.path.join(root, normalized))
    try:
        inside = os.path.commonpath([root, candidate]) == root
    except ValueError:  # Windows 下不同盘符
        inside = False
    if not inside or candidate == root:
        raise ValueError(f"非法的存储对象名（越界路径）: {object_name!r}")
    return candidate


class LocalStorage:
    """本地文件存储（本地模式下媒体走受控端点 /uploads/{object_name}）"""

    def __init__(self):
        os.makedirs(_storage_root(), exist_ok=True)

    async def ensure_bucket(self) -> None:
        print(f"[Storage] Using local filesystem: {_storage_root()}")

    async def upload_file(self, object_name: str, data: bytes, content_type: str = "", size: int = 0) -> str:
        file_path = _secure_local_path(object_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        return f"/uploads/{object_name}"

    async def upload_from_path(self, object_name: str, src_path: str, content_type: str = "") -> str:
        """从磁盘文件入库（上传大文件时避免整包读进内存）。"""
        file_path = _secure_local_path(object_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        os.replace(src_path, file_path)
        return f"/uploads/{object_name}"

    async def delete_file(self, object_name: str) -> None:
        file_path = _secure_local_path(object_name)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            os.remove(file_path)
            # 顺带清理空目录（逐级向上，直到存储根，避免删除项目后残留空目录）
            root = _storage_root()
            d = os.path.dirname(file_path)
            while os.path.abspath(d) != root and os.path.isdir(d):
                try:
                    os.rmdir(d)
                except OSError:
                    break
                d = os.path.dirname(d)

    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        return f"/uploads/{object_name}"

    async def presigned_url_for(self, url: Optional[str], ttl: Optional[int] = None) -> str:
        """local 模式没有"预签名"概念，等价于 HMAC 签名后的 /uploads 链接。"""
        from app.core.media_urls import sign_media_url

        return sign_media_url(url, ttl) or ""


class MinioStorage:
    """MinIO 对象存储服务（M1 起桶为私有，链接一律预签名）

    历史问题：T0 之前 ensure_bucket 会给整桶写入 Principal "*" + s3:GetObject 的
    public-read 策略，等于把全部素材与成片变成公网可下载 —— 只要 URL 泄露就无需
    认证。现在桶保持私有，访问一律走预签名 URL（有 TTL），且已存在的桶会在启动时
    把旧的公开策略删掉。
    """

    def __init__(self):
        self._client = None
        self._presign_client = None

    @property
    def client(self):
        if self._client is None:
            from minio import Minio
            self._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_USE_SSL,
                # 固定 region：否则 minio-py 在预签名前会为解析桶 region 发一次
                # 网络请求，在 async 路由里等于一次隐形阻塞。
                region=settings.MINIO_REGION,
            )
        return self._client

    @property
    def presign_client(self):
        """仅用于签名的客户端：endpoint 必须是**浏览器可达**的主机名。

        SigV4 的签名覆盖 Host 头，所以"用什么主机名签"决定了"浏览器必须用哪个
        主机名访问"。容器内 endpoint 常是 minio:9000（浏览器不可解析），此时用
        MINIO_PUBLIC_ENDPOINT 指定对外地址。
        """
        if self._presign_client is None:
            from minio import Minio
            self._presign_client = Minio(
                endpoint=settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_PUBLIC_USE_SSL or settings.MINIO_USE_SSL,
                region=settings.MINIO_REGION,
            )
        return self._presign_client

    def _public_url(self, object_name: str) -> str:
        """规范的（无签名）对象 URL —— 存进数据库的就是它，读的时候才换预签名。"""
        protocol = "https" if settings.MINIO_USE_SSL else "http"
        return f"{protocol}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAME}/{object_name}"

    def _clear_public_policy(self, bucket_name: str) -> None:
        from minio.error import S3Error

        try:
            self.client.delete_bucket_policy(bucket_name)
            print(f"[Storage] Removed bucket policy on '{bucket_name}' (private bucket)")
        except S3Error as e:
            if e.code in {"NoSuchBucketPolicy", "NoSuchPolicy", "NoSuchBucket"}:
                return
            print(f"[Storage] Failed to clear bucket policy: {e}")

    def _ensure_bucket_sync(self) -> None:
        from minio.error import S3Error

        bucket_name = settings.MINIO_BUCKET_NAME
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                print(f"[Storage] Created private bucket: {bucket_name}")
            else:
                print(f"[Storage] Bucket already exists: {bucket_name}")
            # 不写入任何公开策略；并把历史版本留下的 public-read 策略删掉
            self._clear_public_policy(bucket_name)
        except S3Error as e:
            print(f"[Storage] Bucket check error: {e}")
        except Exception as e:
            print(f"[Storage] Connection error (MinIO may not be running): {e}")

    async def ensure_bucket(self) -> None:
        # minio-py 是同步 SDK，放到线程里，避免启动阶段/请求阶段阻塞事件循环
        await asyncio.to_thread(self._ensure_bucket_sync)

    def _put_object_sync(self, object_name: str, data: bytes, content_type: str, size: int) -> None:
        self.client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            data=io.BytesIO(data),
            length=size or len(data),
            content_type=content_type or "application/octet-stream",
        )

    async def upload_file(self, object_name: str, data: bytes, content_type: str = "", size: int = 0) -> str:
        await asyncio.to_thread(
            self._put_object_sync, object_name, data, content_type, size
        )
        return self._public_url(object_name)

    def _fput_object_sync(self, object_name: str, src_path: str, content_type: str) -> None:
        self.client.fput_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            file_path=src_path,
            content_type=content_type or "application/octet-stream",
        )

    async def upload_from_path(self, object_name: str, src_path: str, content_type: str = "") -> str:
        await asyncio.to_thread(self._fput_object_sync, object_name, src_path, content_type)
        return self._public_url(object_name)

    def _remove_object_sync(self, object_name: str) -> None:
        from minio.error import S3Error

        try:
            self.client.remove_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
            )
        except S3Error as e:
            print(f"[Storage] Delete error: {e}")

    async def delete_file(self, object_name: str) -> None:
        await asyncio.to_thread(self._remove_object_sync, object_name)

    def _presign_sync(self, object_name: str, expires: int) -> str:
        # minio-py 的 expires 参数是 datetime.timedelta，不是秒数。传 int 会抛
        # AttributeError("'int' object has no attribute 'total_seconds'")，被下面
        # 的兜底吞掉后返回空串 —— 表现为线上所有 MinIO 媒体链接都点不开。
        from datetime import timedelta

        try:
            return self.presign_client.presigned_get_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
                expires=timedelta(seconds=expires),
            )
        except Exception as e:
            # 预签名失败（凭据错、region 解析失败、endpoint 不可达）不能让整个
            # 列表接口 500 —— 返回空串，前端显示"无链接"比整页崩掉可接受。
            print(f"[Storage] Presign error: {e}")
            return ""

    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        return await asyncio.to_thread(self._presign_sync, object_name, expires)

    async def presigned_url_for(self, url: Optional[str], ttl: Optional[int] = None) -> str:
        """把库里存的规范 MinIO URL 换成短期预签名 URL。

        失败时返回空串而不是裸 URL：私有桶下裸 URL 一定 403，返回它只会让前端
        显示一个"永远加载不出来"的图，比空更糟。
        """
        if not url:
            return ""
        object_name = extract_object_name(url)
        if not object_name:
            return ""
        expires = int(settings.MEDIA_URL_TTL_SECONDS if ttl is None else ttl)
        return await asyncio.to_thread(self._presign_sync, object_name, expires)


# 根据配置选择存储后端
if settings.STORAGE_TYPE == "local":
    storage_service = LocalStorage()
else:
    storage_service = MinioStorage()


def extract_object_name(url: str) -> str:
    """从存储 URL 提取 object_name（local: /uploads/{object_name}；minio: .../{bucket}/{object_name}）

    预签名 URL 带 `?X-Amz-...` 查询串，必须先剥掉，否则 object_name 会带上参数。
    """
    if not url:
        return ""
    clean = url.split("?", 1)[0].split("#", 1)[0]
    if "/uploads/" in clean:
        return clean.split("/uploads/", 1)[-1]
    marker = f"/{settings.MINIO_BUCKET_NAME}/"
    if marker in clean:
        return clean.split(marker, 1)[-1]
    return ""
