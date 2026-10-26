"""MinIO 私有桶真实 SDK 集成测试（假 S3 服务，不依赖 Docker/MinIO）。

用 minio-py 真客户端（真 SigV4、真 HTTP）打一个标准库实现的极简 S3 端点，
验证三件事：
1. ensure_bucket 只建桶 + 删旧策略，绝不写 public-read 策略；
2. fput_object 真的把字节 PUT 到了 <bucket>/<key>；
3. 预签名 URL 的 Host 是配置的对外地址，且该 URL 能不带头直接 GET 到对象。
"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import urlopen

import importlib

# 注意：不能写 "from app.services import storage_service as svc"，也不能写
# "import app.services.storage_service as svc" —— app/services/__init__.py 把
# 同名属性覆盖成了 storage_service 实例（LocalStorage），两条 import 语法都会
# 先取包属性，拿到的都是实例。只有 importlib.import_module 返回真模块。
svc = importlib.import_module("app.services.storage_service")

from app.core.config import settings


class FakeS3:
    def __init__(self):
        self.bucket_exists = False
        self.objects = {}
        self.requests = []
        self.policies_written = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _record(self, method):
                parsed = urlparse(self.path)
                fake.requests.append((method, parsed.path, parsed.query))
                return parsed

            def _bucket_key(self, parsed):
                parts = parsed.path.lstrip("/").split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 and parts[1] else None
                return bucket, key

            def do_HEAD(self):
                parsed = self._record("HEAD")
                bucket, key = self._bucket_key(parsed)
                if key is None:
                    code = 200 if fake.bucket_exists else 404
                    self.send_response(code)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = fake.objects.get(parsed.path)
                self.send_response(200 if data else 404)
                self.send_header("Content-Length", str(len(data) if data else 0))
                self.end_headers()

            def do_PUT(self):
                parsed = self._record("PUT")
                bucket, key = self._bucket_key(parsed)
                if key is None:
                    if "policy" in parsed.query:
                        fake.policies_written.append(parsed.query)
                    fake.bucket_exists = True
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                fake.objects[parsed.path] = body
                self.send_response(200)
                self.send_header("ETag", '"fake-etag"')
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_DELETE(self):
                parsed = self._record("DELETE")
                if "policy" in parsed.query:
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                parsed = self._record("GET")
                data = fake.objects.get(parsed.path)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self):
        host, port = self.server.server_address[:2]
        return f"{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _storage_with(monkeypatch, s3):
    monkeypatch.setattr(settings, "MINIO_ENDPOINT", s3.endpoint)
    monkeypatch.setattr(settings, "MINIO_USE_SSL", False)
    monkeypatch.setattr(settings, "MINIO_PUBLIC_ENDPOINT", "")
    monkeypatch.setattr(settings, "MINIO_PUBLIC_USE_SSL", False)
    monkeypatch.setattr(settings, "MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setattr(settings, "MINIO_SECRET_KEY", "test-secret")
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "drama-assets")
    monkeypatch.setattr(settings, "MINIO_REGION", "us-east-1")
    return svc.MinioStorage()


def test_private_bucket_roundtrip_with_real_sdk(monkeypatch, tmp_path):
    with FakeS3() as s3:
        storage = _storage_with(monkeypatch, s3)

        # 1) 启动初始化：建私有桶，清旧策略，绝不写公开策略
        asyncio.run(storage.ensure_bucket())
        assert s3.bucket_exists is True
        methods = [(m, p, q) for (m, p, q) in s3.requests]
        assert any(m == "DELETE" and "policy" in q for m, p, q in methods)
        assert s3.policies_written == []

        # 2) 上传落到的 key 与库里的规范 URL
        src = tmp_path / "a.png"
        src.write_bytes(b"fake-png-bytes")
        canonical = asyncio.run(
            storage.upload_from_path("proj-1/a.png", str(src), "image/png")
        )
        assert canonical == f"http://{s3.endpoint}/drama-assets/proj-1/a.png"
        assert s3.objects["/drama-assets/proj-1/a.png"] == b"fake-png-bytes"

        # 3) 预签名：Host 打对外地址；不带头就能取回对象
        presigned = asyncio.run(storage.presigned_url_for(canonical))
        assert presigned.startswith(f"http://{s3.endpoint}/drama-assets/proj-1/a.png?")
        assert "X-Amz-Signature=" in presigned
        with urlopen(presigned) as resp:
            assert resp.status == 200
            assert resp.read() == b"fake-png-bytes"


def test_public_endpoint_used_for_presign_only(monkeypatch, tmp_path):
    with FakeS3() as s3:
        storage = _storage_with(monkeypatch, s3)
        # 浏览器可达的对外端点（另一个 host:port），上传仍走内部端点
        monkeypatch.setattr(settings, "MINIO_PUBLIC_ENDPOINT", "files.example.com:9000")

        src = tmp_path / "b.png"
        src.write_bytes(b"x")
        canonical = asyncio.run(storage.upload_from_path("proj-2/b.png", str(src)))
        assert canonical.startswith(f"http://{s3.endpoint}/drama-assets/")

        presigned = asyncio.run(storage.presigned_url_for(canonical))
        assert presigned.startswith("http://files.example.com:9000/drama-assets/proj-2/b.png?")
