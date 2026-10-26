"""MinIO 私有桶 + 预签名（M1）单元测试。

不依赖真实 MinIO：用假 client 断言行为（不写公开策略、预签名参数正确、
失败时返回空串而不是裸 URL）。
"""
import asyncio
import importlib

# 注意：不能写 "from app.services import storage_service as svc"，也不能写
# "import app.services.storage_service as svc" —— app/services/__init__.py 把
# 同名属性覆盖成了 storage_service 实例（LocalStorage），两条 import 语法都会
# 先取包属性，拿到的都是实例。只有 importlib.import_module 返回真模块。
svc = importlib.import_module("app.services.storage_service")

from app.core import media_urls
from app.core.config import settings


class FakeMinioClient:
    def __init__(self, presigned="http://public:9000/bucket/obj?X-Amz-Signature=abc"):
        self.calls = []
        self.presigned = presigned

    def bucket_exists(self, bucket):
        self.calls.append(("bucket_exists", bucket))
        return False

    def make_bucket(self, bucket):
        self.calls.append(("make_bucket", bucket))

    def delete_bucket_policy(self, bucket):
        self.calls.append(("delete_bucket_policy", bucket))
        raise RuntimeError("NoSuchBucketPolicy: fake")

    def set_bucket_policy(self, bucket, policy):
        self.calls.append(("set_bucket_policy", bucket, policy))

    def presigned_get_object(self, bucket_name, object_name, expires):
        self.calls.append(("presign", bucket_name, object_name, expires))
        return self.presigned


def test_ensure_bucket_never_sets_public_policy():
    storage = svc.MinioStorage()
    fake = FakeMinioClient()
    storage._client = fake
    storage._ensure_bucket_sync()

    names = [c[0] for c in fake.calls]
    assert "make_bucket" in names
    assert "delete_bucket_policy" in names      # 旧公开策略必须被删除
    assert "set_bucket_policy" not in names     # 绝不重新写入公开策略


def test_minio_presigned_url_used_for_canonical_url(monkeypatch):
    storage = svc.MinioStorage()
    fake = FakeMinioClient()
    storage._presign_client = fake

    monkeypatch.setattr(svc, "storage_service", storage)
    monkeypatch.setattr(settings, "STORAGE_TYPE", "minio")

    canonical = f"http://minio:9000/{settings.MINIO_BUCKET_NAME}/proj-1/a.png"
    url = asyncio.run(media_urls.signed_media_url(canonical))

    assert url == fake.presigned
    presign_call = [c for c in fake.calls if c[0] == "presign"][0]
    assert presign_call[1] == settings.MINIO_BUCKET_NAME
    assert presign_call[2] == "proj-1/a.png"
    # 必须换算成 timedelta（minio-py 的 expires 是 timedelta，不是秒数）
    assert presign_call[3].total_seconds() == settings.MEDIA_URL_TTL_SECONDS


def test_presign_failure_returns_empty_not_raw_url(monkeypatch):
    class BrokenClient(FakeMinioClient):
        def presigned_get_object(self, bucket_name, object_name, expires):
            raise RuntimeError("region lookup failed")

    storage = svc.MinioStorage()
    storage._presign_client = BrokenClient()

    monkeypatch.setattr(svc, "storage_service", storage)
    monkeypatch.setattr(settings, "STORAGE_TYPE", "minio")

    canonical = f"http://minio:9000/{settings.MINIO_BUCKET_NAME}/proj-1/a.png"
    assert asyncio.run(media_urls.signed_media_url(canonical)) == ""


def test_local_mode_still_hmac_signs(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    url = asyncio.run(media_urls.signed_media_url("/uploads/proj-1/a.png"))
    assert url is not None and url.startswith("/uploads/proj-1/a.png?exp=")
    assert "&sig=" in url


def test_extract_object_name_strips_presign_query():
    url = (
        f"http://minio:9000/{settings.MINIO_BUCKET_NAME}/proj-1/a.png"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef"
    )
    assert svc.extract_object_name(url) == "proj-1/a.png"
