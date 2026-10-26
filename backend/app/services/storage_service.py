import os
import io
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
    """本地文件存储"""

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


class MinioStorage:
    """MinIO 对象存储服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from minio import Minio
            self._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_USE_SSL,
            )
        return self._client

    def _public_url(self, object_name: str) -> str:
        protocol = "https" if settings.MINIO_USE_SSL else "http"
        return f"{protocol}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAME}/{object_name}"

    async def ensure_bucket(self) -> None:
        from minio.error import S3Error
        bucket_name = settings.MINIO_BUCKET_NAME
        try:
            found = self.client.bucket_exists(bucket_name)
            if not found:
                self.client.make_bucket(bucket_name)
                print(f"[Storage] Created bucket: {bucket_name}")
                # 已知风险（M1 处理）：整桶 public-read，任何拿到 URL 的人都能下载。
                # 正确做法是私有桶 + 短时效签名 URL，需要前端改成按需换取 URL。
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                    }],
                }
                self.client.set_bucket_policy(bucket_name, policy)
            else:
                print(f"[Storage] Bucket already exists: {bucket_name}")
        except S3Error as e:
            print(f"[Storage] Bucket check error: {e}")
        except Exception as e:
            print(f"[Storage] Connection error (MinIO may not be running): {e}")

    async def upload_file(self, object_name: str, data: bytes, content_type: str = "", size: int = 0) -> str:
        data_stream = io.BytesIO(data)
        self.client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            data=data_stream,
            length=size or len(data),
            content_type=content_type or "application/octet-stream",
        )
        return self._public_url(object_name)

    async def upload_from_path(self, object_name: str, src_path: str, content_type: str = "") -> str:
        self.client.fput_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            file_path=src_path,
            content_type=content_type or "application/octet-stream",
        )
        return self._public_url(object_name)

    async def delete_file(self, object_name: str) -> None:
        from minio.error import S3Error
        try:
            self.client.remove_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
            )
        except S3Error as e:
            print(f"[Storage] Delete error: {e}")

    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        from minio.error import S3Error
        try:
            return self.client.presigned_get_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
                expires=expires,
            )
        except S3Error:
            return ""


# 根据配置选择存储后端
if settings.STORAGE_TYPE == "local":
    storage_service = LocalStorage()
else:
    storage_service = MinioStorage()


def extract_object_name(url: str) -> str:
    """从存储 URL 提取 object_name（local: /uploads/{object_name}；minio: .../{bucket}/{object_name}）"""
    if "/uploads/" in url:
        return url.split("/uploads/", 1)[-1]
    marker = f"/{settings.MINIO_BUCKET_NAME}/"
    if marker in url:
        return url.split(marker, 1)[-1]
    return ""
