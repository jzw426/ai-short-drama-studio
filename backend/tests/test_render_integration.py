"""渲染链路的**真实**集成测试：真 ffmpeg + 真落盘 + 真读库。

和其他测试不同，这里不 monkeypatch 掉 ffmpeg —— 目的就是证明
"配置生效、镜头绑定生效、字幕/ BGM 真的进了成片、成片真的在存储里"。

依赖：本机 ffmpeg（开发者机器上由 imageio-ffmpeg 提供，生产镜像由
Dockerfile 安装）。没有 ffmpeg 时整个文件 skip，而不是假装通过。
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from app.core.config import settings

try:  # imageio-ffmpeg 只是开发期的 ffmpeg 来源，不是运行依赖
    import imageio_ffmpeg

    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover - 有系统 ffmpeg 的环境走这里
    import shutil

    FFMPEG = shutil.which("ffmpeg")

pytestmark = pytest.mark.skipif(not FFMPEG, reason="本机没有 ffmpeg，跳过真实渲染测试")


def _run_ffmpeg(*args: str) -> None:
    result = subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=180,
    )
    assert result.returncode == 0, f"ffmpeg 失败: {result.stderr[-800:]}"


def _make_clip(path: Path, seconds: float = 1.0, size: str = "320x240", audio: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={seconds}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    _run_ffmpeg(*args, str(path))


def _probe(path: Path) -> str:
    """没有 ffprobe 也能验：ffmpeg -i 把元信息打印在 stderr。"""
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=60,
    )
    return result.stderr


def _duration_seconds(info: str) -> float:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    assert match, info[-500:]
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


@pytest.fixture
def render_env(tmp_path, monkeypatch):
    """临时 sqlite + 临时存储目录 + 本机 ffmpeg。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.core.database as database

    db_path = tmp_path / "test.db"
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(database, "async_session", factory)
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(uploads))
    monkeypatch.setattr(settings, "FFMPEG_PATH", FFMPEG)
    # 本机没有 ffprobe：强制走进 ffmpeg -i 的降级路径
    monkeypatch.setattr(settings, "FFPROBE_PATH", str(tmp_path / "no-ffprobe"))

    from app.core.database import Base
    from app.models import asset, ai_usage, character, project, script, storyboard, user  # noqa: F401

    import types

    yield types.SimpleNamespace(engine=engine, factory=factory, uploads=uploads)


async def _seed(env, *, with_video: bool = True, dialogue: str = "别走。"):
    from app.core.database import Base
    from app.models.project import Project
    from app.models.script import Scene, Script
    from app.models.storyboard import Shot, Storyboard

    async with env.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    project_id = str(uuid.uuid4())
    async with env.factory() as session:
        session.add(
            Project(
                id=project_id,
                title="雨夜",
                description="",
                owner_id=str(uuid.uuid4()),
                status="draft",
            )
        )
        script = Script(project_id=project_id, title="第一集", content="", word_count=0)
        session.add(script)
        await session.flush()
        session.add(
            Scene(
                script_id=script.id,
                scene_number=1,
                title="街角",
                summary="",
                content="",
                dialogue=dialogue,
                duration=4,
                sort_order=0,
            )
        )
        board = Storyboard(project_id=project_id, canvas_state="{}")
        session.add(board)
        await session.flush()
        for number in (1, 2):
            session.add(
                Shot(
                    storyboard_id=board.id,
                    shot_number=number,
                    label=f"镜头{number}",
                    description=f"第{number}镜 雨夜街道",
                    duration=3.0,
                    scene_ref="#1",
                    video_url=f"/uploads/segments/seg{number}.mp4" if with_video else None,
                    sort_order=number,
                )
            )
        await session.commit()
    return project_id


@pytest.mark.asyncio
async def test_execute_render_produces_real_video(render_env):
    """端到端：两个镜头 → 统一 1080x1920/24fps → 烧字幕 → 混 BGM → 落存储。"""
    from app.services.render_service import render_service

    env = render_env
    project_id = await _seed(env)
    for number in (1, 2):
        _make_clip(env.uploads / "segments" / f"seg{number}.mp4", seconds=1.0)
    _make_clip(env.uploads / "bgm" / "theme.wav", seconds=3.0, audio=True)

    task_id = "task-e2e"
    results = await render_service.execute_render(
        task_id,
        project_id,
        {
            "resolution": "1080x1920",
            "aspect_ratio": "9:16",
            "fps": 24,
            "quality": "low",
            "visual_style": "写实",
            "add_subtitles": True,
            "subtitle_source": "dialogue",
            "add_bgm": True,
            "bgm_source": "/uploads/bgm/theme.wav",
        },
    )

    assert results["status"] == "completed", results.get("errors")
    assert not results["errors"]
    assert results["output_url"] == (
        f"/uploads/renders/{project_id}/{task_id}/output.mp4"
    )

    output = env.uploads / "renders" / project_id / task_id / "output.mp4"
    assert output.exists() and output.stat().st_size > 10_000

    info = _probe(output)
    # config 真的生效了：不是跟着素材的 320x240 走
    assert "1080x1920" in info
    assert "24 fps" in info
    duration = _duration_seconds(info)
    assert 1.7 <= duration <= 2.8, info[-400:]
    # BGM 混入了 → 成片必须有音轨
    assert "Audio:" in info

    # 字幕步骤必须真的成功（失败会被降级成 warnings，而不是让整单失败）。
    # 成功渲染不应产生任何 warning：说明 dialogue 取到了台词、SRT 写成、烧制成功。
    assert results["warnings"] == [], results["warnings"]

    # srt 随片交付：文件落在成片同目录，结果里给出可直接下载的签名地址
    srt_file = env.uploads / "renders" / project_id / task_id / "subtitle.srt"
    assert srt_file.exists()
    assert "别走。" in srt_file.read_text(encoding="utf-8")
    subtitle_url = results.get("subtitle_url") or ""
    assert f"/uploads/renders/{project_id}/{task_id}/subtitle.srt" in subtitle_url
    assert "sig=" in subtitle_url and "exp=" in subtitle_url


@pytest.mark.asyncio
async def test_execute_render_soft_subtitles_muxs_track(render_env):
    """soft 模式：不碰画面，只封一条 mov_text 软字幕轨，srt 仍然随片交付。"""
    from app.services.render_service import render_service

    env = render_env
    project_id = await _seed(env)
    for number in (1, 2):
        _make_clip(env.uploads / "segments" / f"seg{number}.mp4", seconds=1.0)
    _make_clip(env.uploads / "bgm" / "theme.wav", seconds=3.0, audio=True)

    task_id = "task-soft"
    results = await render_service.execute_render(
        task_id,
        project_id,
        {
            "resolution": "1080x1920",
            "aspect_ratio": "9:16",
            "fps": 24,
            "quality": "low",
            "add_subtitles": True,
            "subtitle_source": "dialogue",
            "subtitle_mode": "soft",
            # 混 BGM 发生在字幕之后：这里顺带守住"混音不能把软字幕轨丢掉"
            "add_bgm": True,
            "bgm_source": "/uploads/bgm/theme.wav",
        },
    )

    assert results["status"] == "completed", results.get("errors")
    assert results["warnings"] == [], results["warnings"]

    output = env.uploads / "renders" / project_id / task_id / "output.mp4"
    assert output.exists()
    info = _probe(output)
    # 软字幕轨真的被封装进来了：mov_text 可以在播放器里开关，画面本身没被烧字
    assert "Subtitle: mov_text" in info, info[-600:]
    assert "1080x1920" in info

    srt_file = env.uploads / "renders" / project_id / task_id / "subtitle.srt"
    assert srt_file.exists(), sorted(
        str(path.relative_to(env.uploads)) for path in (env.uploads / "renders").rglob("*")
    )
    assert "别走。" in srt_file.read_text(encoding="utf-8")
    subtitle_url = results.get("subtitle_url") or ""
    assert f"/uploads/renders/{project_id}/{task_id}/subtitle.srt" in subtitle_url
    assert "sig=" in subtitle_url and "exp=" in subtitle_url


@pytest.mark.asyncio
async def test_execute_render_reports_unbound_shot(render_env, monkeypatch):
    """没绑定素材又没有 AI Key：必须给出"镜头 N 未绑定素材"，而不是空 200。"""
    import sys

    from app.services.render_service import render_service

    render_module = sys.modules["app.services.render_service"]

    async def unavailable(**kwargs):
        raise render_module.AIUnavailableError("所有 provider 均不可用")

    monkeypatch.setattr(render_module.ai_service, "generate_video", unavailable)

    env = render_env
    project_id = await _seed(env, with_video=False, dialogue="")

    results = await render_service.execute_render(
        "task-unbound", project_id, {"add_subtitles": False}
    )

    assert results["status"] == "failed"
    assert any("未绑定素材" in e for e in results["errors"])
