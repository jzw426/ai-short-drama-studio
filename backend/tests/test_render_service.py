"""渲染服务的可测纯逻辑 + 取消/断点行为。

不碰真实 FFmpeg（真跑在 test_render_service_integration.py）：这里只验证
"钱和数据的边界"——取消必须真的停下来（而不是继续烧 AI），断点命中的镜头
不能再调一次 AI，素材地址只接受受控来源。
"""
import os
import sys

import pytest

from app.services.render_service import (
    RenderCancelled,
    RenderService,
    RenderStepError,
    build_spec,
    extract_dialogue,
)

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


def test_srt_by_description_splits_lines_into_cues(service):
    shots = [{"duration": 2.0, "description": "雨夜 街道\n霓虹闪烁", "label": "镜头1"}]
    srt, missing = service._generate_srt(shots, source="description")
    # 换行也是切句边界：两行各占 2s 里按字符数分到的时长（5:4 → 1.111s / 0.889s）
    assert "雨夜 街道" in srt.splitlines()
    assert "霓虹闪烁" in srt.splitlines()
    assert "00:00:00,000 --> 00:00:01,111" in srt
    assert "00:00:01,111 --> 00:00:02,000" in srt
    assert missing == 0


def test_srt_by_label_and_none(service):
    shots = [{"duration": 1.0, "description": "画面描述", "label": "镜头A"}]
    srt, _ = service._generate_srt(shots, source="label")
    assert "镜头A" in srt
    # source=none：明确要求不生成字幕
    srt_none, _ = service._generate_srt(shots, source="none")
    assert srt_none == ""


def test_srt_uses_dialogue_and_falls_back_when_missing(service):
    shots = [
        {"duration": 2.0, "description": "她转身离开", "label": "镜头1", "dialogue": "别走。"},
        {"duration": 1.5, "description": "雨落", "label": "镜头2", "dialogue": ""},
    ]
    srt, missing = service._generate_srt(shots, source="dialogue")
    assert "别走。" in srt
    # 没有台词的第二镜回退到画面描述，并计数，避免"无声字幕"被当成正常
    assert "雨落" in srt
    assert missing == 1


def test_srt_timeline_follows_real_clip_durations(service):
    """成片时间轴按片段真实时长累计，而不是分镜上标称的 duration。"""
    shots = [
        {"duration": 3.0, "description": "第一镜", "label": "1"},
        {"duration": 3.0, "description": "第二镜", "label": "2"},
    ]
    srt, _ = service._generate_srt(shots, source="label", durations=[1.0, 2.5])
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:01,000 --> 00:00:03,500" in srt


def test_extract_dialogue_dedupes_and_keeps_order():
    text = (
        "场景一\n"
        "「今天不回去。」她说。\n"
        "『那就别回去。』\n"
        "「今天不回去。」重复的不要。\n"
        "没有引号的旁白不算台词。"
    )
    assert extract_dialogue(text) == "今天不回去。\n那就别回去。"


def test_build_spec_defaults_to_vertical_9_16():
    spec, warnings = build_spec({"resolution": "1920x1080", "aspect_ratio": "9:16"})
    assert (spec.width, spec.height) == (1080, 1920)
    # 横屏 resolution + 竖屏比例属于"方向冲突"，必须给用户提示（而不是默默改写）
    assert any("方向不一致" in w for w in warnings)


def test_build_spec_uses_ratio_alone_silently():
    spec, warnings = build_spec({"resolution": "1080x1920", "aspect_ratio": "9:16"})
    assert (spec.width, spec.height) == (1080, 1920)
    assert warnings == []


def test_build_spec_clamps_and_records_warnings():
    spec, warnings = build_spec(
        {"resolution": "9999x100", "aspect_ratio": "bad", "fps": 240, "quality": "ultra"}
    )
    assert spec.width <= 4096 and spec.height >= 144
    assert spec.fps == 60
    assert spec.crf == 20  # quality 未知回退 high
    assert any("超出" in w for w in warnings)
    assert any("无法解析" in w for w in warnings)
    assert any("fps" in w for w in warnings)
    assert any("quality" in w for w in warnings)


def test_build_spec_style_and_font_scale():
    spec, _ = build_spec(
        {"resolution": "1080x1920", "aspect_ratio": "9:16", "visual_style": "电影级（Cinematic）"}
    )
    assert "eq=contrast" in spec.style_filter
    assert spec.subtitle_font_size >= 30
    assert "scale=1080:1920" in spec.video_filter()


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
    """断点命中：复用既有片段，绝不再调一次 AI（这是重试不重复烧钱的关键）。"""

    async def boom(**kwargs):
        raise AssertionError("断点命中却仍调用了 AI")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", boom)

    async def fake_stage(url, temp_dir, idx, source_kind):
        path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        with open(path, "wb") as fh:
            fh.write(b"fake")
        return path

    monkeypatch.setattr(service, "_stage_segment", fake_stage)

    shots = [{"shot_number": 1, "duration": 3.0, "description": "d", "label": "l"}]
    spec, _ = build_spec({})
    segments = await service._render_segments(
        shots, str(tmp_path), spec, None, None, {1: "https://cdn/x.mp4"}, "p1"
    )
    assert segments[0]["status"] == "success"
    assert segments[0]["video_url"] == "https://cdn/x.mp4"


@pytest.mark.asyncio
async def test_render_segments_explains_unbound_shot(service, monkeypatch, tmp_path):
    """没有绑定素材、AI 又不可用时，错误必须能定位到镜头和原因（不许静默 200）。"""

    async def unavailable(**kwargs):
        raise RENDER_MODULE.AIUnavailableError("所有 provider 均不可用")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", unavailable)

    spec, _ = build_spec({})
    shots = [{"shot_number": 2, "duration": 3.0, "description": "d", "label": "l"}]
    segments = await service._render_segments(
        shots, str(tmp_path), spec, None, None, {}, "p1"
    )
    assert segments[0]["status"] == "failed"
    assert "镜头 2" in segments[0]["error"]
    assert "未绑定素材" in segments[0]["error"]


@pytest.mark.asyncio
async def test_ai_video_is_persisted_before_entering_checkpoint(
    service, monkeypatch, tmp_path
):
    """M4-1 回归：AI 视频必须先转存到自有存储，再作为片段地址返回。

    旧实现把 provider 的 CDN 链接原样写进 checkpoint，链接 TTL 到点后
    断点续渲必然 404 —— 恰好发生在最贵的那条路径上。
    """
    seen = {}

    async def fake_generate(**kwargs):
        return "https://provider-cdn.example/tmp/abc.mp4"

    async def fake_persist(url, prefix, **kwargs):
        seen["url"] = url
        seen["prefix"] = prefix
        return "/uploads/ai/videos/p9/persisted.mp4"

    async def fake_stage(url, temp_dir, idx, source_kind):
        path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        with open(path, "wb") as fh:
            fh.write(b"fake")
        return path

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", fake_generate)
    monkeypatch.setattr(RENDER_MODULE, "persist_remote_media", fake_persist)
    monkeypatch.setattr(service, "_stage_segment", fake_stage)

    spec, _ = build_spec({})
    shots = [{"shot_number": 1, "duration": 3.0, "description": "d", "label": "l"}]
    segments = await service._render_segments(
        shots, str(tmp_path), spec, None, None, {}, "p9"
    )

    assert seen["url"] == "https://provider-cdn.example/tmp/abc.mp4"
    assert seen["prefix"].startswith("ai/videos/p9/")
    assert segments[0]["video_url"] == "/uploads/ai/videos/p9/persisted.mp4"
    assert segments[0]["source"] == "local"


def test_source_kind_rejects_escape_and_foreign_schemes(service):
    assert service._source_kind("https://cdn/x.mp4") == ("http", "https://cdn/x.mp4")
    assert service._source_kind("file:///etc/passwd") is None
    assert service._source_kind("javascript:alert(1)") is None
    # /uploads/ 下的路径穿越必须解析失败
    assert service._source_kind("/uploads/../../etc/passwd") is None


def test_source_kind_maps_minio_url_to_object(service, monkeypatch):
    """MinIO 私有桶：规范 URL 必须解析成 ("object", object_name)，走 SDK 取。

    回归背景：桶私有化之后，把规范 URL 当普通 http 下载一定 403，
    表现为"任务失败在镜头素材下载"，而素材其实好好的躺在桶里。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_TYPE", "minio")
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "ai-drama-studio-assets")

    kind = service._source_kind(
        "http://minio:9000/ai-drama-studio-assets/proj/abc.mp4?X-Amz-Signature=x"
    )
    assert kind == ("object", "proj/abc.mp4")

    # 非本桶/第三方外链仍然按 http 处理（比如 Kling 回传的 CDN 地址）
    assert service._source_kind("https://cdn.example.com/x.mp4") == (
        "http",
        "https://cdn.example.com/x.mp4",
    )


def test_render_step_error_str_contains_stage_and_detail():
    exc = RenderStepError("归一化失败", "Invalid data found")
    assert str(exc) == "归一化失败: Invalid data found"
