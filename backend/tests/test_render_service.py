"""渲染服务的可测纯逻辑 + 取消/断点行为。

不碰真实 FFmpeg 与 AI：这里只验证"钱和数据的边界"——
取消必须真的停下来（而不是继续烧 AI），断点命中的镜头不能再调一次 AI。
"""
import os
import sys

import pytest

from app.services.render_service import RenderCancelled, RenderService

# 注意：`import app.services.render_service as m` 拿到的是包属性，
# 而 app.services.render_service 这个名字被模块级单例覆盖了 → 会拿到实例而不是模块。
RENDER_MODULE = sys.modules["app.services.render_service"]


@pytest.fixture
def service():
    return RenderService()


def test_resume_map_keeps_only_usable_segments():
    resume = {
        "segments": [
            {"shot_number": 1, "video_url": "u1", "status": "success"},
            {"shot_number": 2, "video_url": "u2", "status": "failed"},
            {"shot_number": "bad", "video_url": "u3", "status": "success"},
            {"shot_number": 3, "video_url": "", "status": "success"},
            {"shot_number": "4", "video_url": "u4"},
        ]
    }
    assert RenderService._resume_map(resume) == {1: "u1", 4: "u4"}


def test_resume_map_tolerates_none():
    assert RenderService._resume_map(None) == {}


def test_format_timestamp_carries_over():
    assert RenderService._format_timestamp(0) == "00:00:00,000"
    assert RenderService._format_timestamp(1.5) == "00:00:01,500"
    # 59.9996s 四舍五入到 60s，必须进位到 1 分钟而不是输出 00:00:60,000
    assert RenderService._format_timestamp(59.9996) == "00:01:00,000"
    assert RenderService._format_timestamp(3661.25) == "01:01:01,250"


def test_srt_by_description_is_single_line(service):
    shots = [{"duration": 2.0, "description": "雨夜 街道\n霓虹闪烁", "label": "镜头1"}]
    srt = service._generate_srt(shots, source="description")
    # 换行被折叠成空格，且字幕正文自成一行（SRT 块之间本来就有换行）
    assert "雨夜 街道 霓虹闪烁" in srt.splitlines()
    assert "00:00:00,000 --> 00:00:02,000" in srt


def test_srt_by_label_and_none(service):
    shots = [{"duration": 1.0, "description": "画面描述", "label": "镜头A"}]
    assert "镜头A" in service._generate_srt(shots, source="label")
    # source=none：明确要求不生成字幕
    assert service._generate_srt(shots, source="none") == ""


@pytest.mark.asyncio
async def test_execute_render_stops_before_any_ai_call(service, monkeypatch):
    """取消标志已置位时，必须在调 AI 之前就抛 RenderCancelled。"""

    async def boom(**kwargs):
        raise AssertionError("取消后不应再调用 AI 视频生成")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", boom)

    calls = []

    async def cancel_check():
        calls.append(1)
        return True

    with pytest.raises(RenderCancelled):
        await service.execute_render(
            task_id="t1", project_id="p1", config={}, cancel_check=cancel_check
        )
    assert calls, "cancel_check 必须被调用"


@pytest.mark.asyncio
async def test_render_segments_reuses_checkpoint_without_ai(service, monkeypatch, tmp_path):
    """断点命中：下载复用既有片段，绝不再调一次 AI（这是重试不重复烧钱的关键）。"""

    async def boom(**kwargs):
        raise AssertionError("断点命中却仍调用了 AI")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", boom)

    async def fake_download(url, temp_dir, idx):
        path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        with open(path, "wb") as fh:
            fh.write(b"fake")
        return path

    monkeypatch.setattr(service, "_download_segment", fake_download)

    shots = [{"shot_number": 1, "duration": 3.0, "description": "d", "label": "l"}]
    segments = await service._render_segments(
        shots, str(tmp_path), {}, None, None, {1: "https://cdn/x.mp4"}
    )
    assert segments[0]["status"] == "success"
    assert segments[0]["video_url"] == "https://cdn/x.mp4"
