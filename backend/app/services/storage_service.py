import os
import io
import shutil
from typing import Optional

from app.core.config import settings


class LocalStorage:
    """本地文件存储"""

    def __init__(self):
        os.makedirs(settings.STORAGE_LOCAL_PATH, exist_ok=True)

    async def ensure_bucket(self) -> None:
        print(f"[Storage] Using local filesystem: {settings.STORAGE_LOCAL_PATH}")

    async def upload_file(self, object_name: str, data: bytes, content_type: str = "", size: int = 0) -> str:
        file_path = os.path.join(settings.STORAGE_LOCAL_PATH, object_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        return f"/uploads/{object_name}"

    async def delete_file(self, object_name: str) -> None:
        file_path = os.path.join(settings.STORAGE_LOCAL_PATH, object_name)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            os.remove(file_path)
            # 顺带清理空目录（逐级向上，直到存储根，避免删除项目后残留空目录）
            root = os.path.abspath(settings.STORAGE_LOCAL_PATH)
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

    async def ensure_bucket(self) -> None:
        from minio.error import S3Error
        bucket_name = settings.MINIO_BUCKET_NAME
        try:
            found = self.client.bucket_exists(bucket_name)
            if not found:
                self.client.make_bucket(bucket_name)
                print(f"[Storage] Created bucket: {bucket_name}")
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
        from minio.error import S3Error
        data_stream = io.BytesIO(data)
        self.client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            data=data_stream,
            length=size or len(data),
            content_type=content_type,
        )
        protocol = "https" if settings.MINIO_USE_SSL else "http"
        return f"{protocol}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAME}/{object_name}"

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
    if "ai-drama-studio-assets/" in url:
        return url.split("ai-drama-studio-assets/", 1)[-1]
    return ""
