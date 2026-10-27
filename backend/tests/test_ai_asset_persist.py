"""M4-1：AI 产物（第三方 CDN 链接）必须转存到我们自己的存储。

不转存的后果不是"多一次下载"，而是素材寿命被 provider 掌控：链接 TTL 到点后
形象库空空、断点续渲 404。这里用本地 HTTP 服务模拟 provider CDN，断言落盘、
幂等、体积上限、状态码透传。
"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.config import settings
from app.services.storage_service import LocalStorage

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\x0d\x0a-\xb4\x00\x00\x00\x00IEND\xaeB\x60\x82"
)


def _make_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class _CdnHandler(BaseHTTPRequestHandler):
    """极简 provider CDN：/img.png、/noext、/fake.bin、/missing、/huge。"""

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/missing":
            self.send_error(404, "gone")
            return
        if path == "/huge":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(10 * 1024 * 1024))
            self.end_headers()
            self.wfile.write(b"\x00" * 1024)
            return
        body = PNG_BYTES
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默，避免污染 pytest 输出
        pass


@pytest.fixture
def cdn():
    server, thread = _make_server(_CdnHandler)
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(root))
    # 模块引用：app.services.__init__ 把 storage_service 名字覆盖成了实例
    module = sys.modules["app.services.storage_service"]
    return module, LocalStorage(), root


@pytest.mark.asyncio
async def test_persist_remote_image_lands_in_own_storage(cdn, store):
    module, _storage, root = store

    url = await module.persist_remote_media(f"{cdn}/img.png", "ai/images/p1/abc")

    assert url.startswith("/uploads/ai/images/p1/abc"), url
    assert url.endswith(".png"), "扩展名应来自 Content-Type"
    saved = root / url[len("/uploads/"):]
    assert saved.read_bytes() == PNG_BYTES


@pytest.mark.asyncio
async def test_content_type_wins_over_misleading_suffix(cdn, store):
    module, _storage, root = store

    url = await module.persist_remote_media(f"{cdn}/fake.bin", "ai/videos/p1/x")

    assert url.endswith(".png"), url
    assert (root / url[len("/uploads/"):]).exists()


@pytest.mark.asyncio
async def test_no_extension_url_uses_content_type(cdn, store):
    module, _storage, _root = store

    url = await module.persist_remote_media(f"{cdn}/noext", "ai/images/p2/xyz")

    assert url.endswith(".png"), url


@pytest.mark.asyncio
async def test_persist_is_idempotent_for_own_urls(cdn, store):
    module, _storage, root = store

    first = await module.persist_remote_media(f"{cdn}/img.png", "ai/images/p3/one")
    again = await module.persist_remote_media(first, "ai/images/p3/two")

    assert again == first
    assert not (root / "ai/images/p3/two.png").exists(), "已属自有地址不应重复下载落盘"


@pytest.mark.asyncio
async def test_http_error_propagates(cdn, store):
    module, _storage, _root = store

    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        await module.persist_remote_media(f"{cdn}/missing", "ai/images/p4/x")


@pytest.mark.asyncio
async def test_size_limit_rejected_before_download(cdn, store):
    module, _storage, _root = store

    with pytest.raises(ValueError, match="过大|超过上限"):
        await module.persist_remote_media(
            f"{cdn}/huge", "ai/videos/p5/big", max_bytes=1024 * 1024
        )


@pytest.mark.asyncio
async def test_non_http_url_rejected(store):
    module, _storage, _root = store

    with pytest.raises(ValueError):
        await module.persist_remote_media("file:///etc/passwd", "ai/images/p6/x")
    with pytest.raises(ValueError):
        await module.persist_remote_media("", "ai/images/p6/x")
