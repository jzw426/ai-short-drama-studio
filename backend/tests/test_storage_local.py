"""本地存储的落盘语义：跨卷/跨盘符也必须能入库。"""
import os

import pytest

from app.core.config import settings
from app.services.storage_service import LocalStorage


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(root))
    return LocalStorage(), root


@pytest.mark.asyncio
async def test_upload_from_path_moves_file(store, tmp_path):
    storage, root = store
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video-bytes")

    url = await storage.upload_from_path("renders/p/t/output.mp4", str(src))

    assert url == "/uploads/renders/p/t/output.mp4"
    assert (root / "renders/p/t/output.mp4").read_bytes() == b"video-bytes"
    assert not src.exists(), "入库后临时文件必须被移除"


@pytest.mark.asyncio
async def test_upload_from_path_survives_cross_device_move(store, tmp_path, monkeypatch):
    """模拟 os.replace 跨卷失败（WinError 17 / EXDEV）：必须退化为复制+删除。"""
    storage, root = store
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video-bytes")

    # app.services.__init__ 把 "storage_service" 属性覆盖成了实例，
    # 必须从 sys.modules 拿真模块。
    import sys

    module = sys.modules["app.services.storage_service"]

    def cross_device(src_path, dst_path):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(module.os, "replace", cross_device)

    url = await storage.upload_from_path("renders/p/t/output.mp4", str(src))

    assert url == "/uploads/renders/p/t/output.mp4"
    assert (root / "renders/p/t/output.mp4").read_bytes() == b"video-bytes"
    assert not src.exists()
