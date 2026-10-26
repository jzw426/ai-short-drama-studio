"""Celery 任务层的真实闭环：任务被真的执行、状态真的落库。

这里用 `task_always_eager=True` 把 worker 逻辑跑在当前进程里（本机没有
Redis，eager 是唯一能不经 broker 验证任务体的方式；broker 级验证见
scripts/verify_render_worker.py）。断言的是"任务跑完后库里的 RenderTask
到底是什么状态"——而不是"函数有没有被调用"。
"""
from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

try:
    import imageio_ffmpeg

    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover
    import shutil

    FFMPEG = shutil.which("ffmpeg")

# 只有真正要跑 ffmpeg 的闭环用例才依赖它；下面的字幕排版纯单测不该被整模块拖下水
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="本机没有 ffmpeg，跳过任务闭环测试")

# app/services/__init__.py 把同名实例挂在包属性上，直接 import 模块拿到的是实例
RENDER_MODULE = importlib.import_module("app.services.render_service")


def _clip(path: Path, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-600:]


@pytest.fixture
def env(tmp_path, monkeypatch):
    import types

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.core.database as database
    import app.tasks.render_task as render_task_module

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'task.db').as_posix()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(database, "async_session", factory)
    monkeypatch.setattr(render_task_module, "celery_async_session", factory)
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(uploads))
    monkeypatch.setattr(settings, "FFMPEG_PATH", FFMPEG)
    monkeypatch.setattr(settings, "FFPROBE_PATH", str(tmp_path / "no-ffprobe"))

    from app.core.database import Base
    from app.models import asset, ai_usage, character, project, script, storyboard, user  # noqa: F401

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_tables())
    return types.SimpleNamespace(engine=engine, factory=factory, uploads=uploads)


def _seed(env, *, shots: int = 2) -> tuple[str, str]:
    from app.models.asset import RenderTask
    from app.models.project import Project
    from app.models.storyboard import Shot, Storyboard

    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    async def _run():
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
            board = Storyboard(project_id=project_id, canvas_state="{}")
            session.add(board)
            await session.flush()
            for number in range(1, shots + 1):
                session.add(
                    Shot(
                        storyboard_id=board.id,
                        shot_number=number,
                        label=f"镜头{number}",
                        description="雨夜街道",
                        duration=1.0,
                        video_url=f"/uploads/segments/seg{number}.mp4",
                        sort_order=number,
                    )
                )
            session.add(
                RenderTask(
                    id=task_id,
                    project_id=project_id,
                    name="第一次渲染",
                    status="queued",
                    progress=0.0,
                    config={"add_subtitles": False, "add_bgm": False, "quality": "low"},
                    idempotency_key="idem-1",
                    attempt=0,
                    checkpoint={},
                )
            )
            await session.commit()

    asyncio.run(_run())
    for number in range(1, shots + 1):
        _clip(env.uploads / "segments" / f"seg{number}.mp4")
    return project_id, task_id


def _load_task(env, task_id: str):
    from app.models.asset import RenderTask

    async def _run():
        async with env.factory() as session:
            return await session.get(RenderTask, task_id)

    return asyncio.run(_run())


@requires_ffmpeg
def test_celery_task_completes_and_persists_output(env):
    """任务跑完必须自己把 status/progress/output_url/end_time 写进库。"""
    from app.tasks.celery_app import celery_app
    from app.tasks.render_task import execute_render

    project_id, task_id = _seed(env)

    celery_app.conf.task_always_eager = True
    try:
        result = execute_render.apply(args=[task_id])
    finally:
        celery_app.conf.task_always_eager = False

    assert result.state == "SUCCESS", result.traceback()

    task = _load_task(env, task_id)
    assert task is not None
    assert task.status == "completed", task.error_message
    assert task.progress == 100.0
    assert task.output_url == f"/uploads/renders/{project_id}/{task_id}/output.mp4"
    assert task.output_url and (env.uploads / "renders" / project_id / task_id / "output.mp4").exists()
    assert task.end_time is not None
    assert task.duration is not None and task.duration > 0
    assert not task.error_message


@requires_ffmpeg
def test_celery_task_records_failure_without_output(env):
    """渲染失败必须落 failed + 可读原因，且不能留下"completed 但没文件"的状态。"""
    from app.tasks.celery_app import celery_app
    from app.tasks.render_task import execute_render

    project_id, task_id = _seed(env, shots=0)

    celery_app.conf.task_always_eager = True
    try:
        execute_render.apply(args=[task_id])
    finally:
        celery_app.conf.task_always_eager = False

    task = _load_task(env, task_id)
    assert task.status == "failed"
    assert task.error_message
    assert "没有可渲染的镜头" in task.error_message
    assert task.output_url is None


@requires_ffmpeg
def test_idempotency_key_is_unique_per_project(env):
    """并发重复提交由数据库唯一索引兜底：同一 (project, key) 只能有一个任务。"""
    from app.models.asset import RenderTask

    project_id, _ = _seed(env)

    async def _insert_twice():
        async with env.factory() as session:
            session.add(
                RenderTask(
                    project_id=project_id,
                    name="A",
                    status="queued",
                    progress=0.0,
                    config={},
                    idempotency_key="dup-key",
                    checkpoint={},
                )
            )
            await session.commit()
        async with env.factory() as session:
            session.add(
                RenderTask(
                    project_id=project_id,
                    name="B",
                    status="queued",
                    progress=0.0,
                    config={},
                    idempotency_key="dup-key",
                    checkpoint={},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

    asyncio.run(_insert_twice())


# ---------------------------------------------------------------------------
# 字幕排版单测：切句 / 时间轴 / 折行 / subtitle_mode
# 这些不需要 ffmpeg，比闭环用例快得多，所以不挂 requires_ffmpeg
# ---------------------------------------------------------------------------


def test_split_subtitles_on_punctuation_and_newline():
    split = RENDER_MODULE._split_subtitle_sentences
    assert split("别走。雨很大！你要去哪？") == ["别走。", "雨很大！", "你要去哪？"]
    assert split("算了，走吧。") == ["算了，", "走吧。"]
    assert split("Go home. Now!") == ["Go home.", "Now!"]
    # 换行也是切句点：一行一个语义单元时不该被拼回一句
    assert split("第一句\n第二句，第三句。") == ["第一句", "第二句，", "第三句。"]
    # 句末标点和右引号属于前一句，不能切出只有「」的空壳
    assert split("「别走。」她说。") == ["「别走。」", "她说。"]
    # 连续标点（省略号）不单独成条
    assert split("等等……再说吧。") == ["等等……", "再说吧。"]
    # 没有标点也没有换行：整段一条
    assert split("没有标点的一整段") == ["没有标点的一整段"]
    assert split("   ") == []


def test_srt_splits_shot_time_by_char_count():
    service = RENDER_MODULE.RenderService()
    shots = [{"duration": 6.0, "dialogue": "第一句话。第二句话更长一些。"}]
    srt, missing = service._generate_srt(shots, source="dialogue")
    # 5 : 9 个字符 → 2.143s / 3.857s；末条严格收在镜头末尾
    assert "00:00:00,000 --> 00:00:02,143" in srt
    assert "00:00:02,143 --> 00:00:06,000" in srt
    assert "第一句话。" in srt.splitlines()
    assert "第二句话更长一些。" in srt.splitlines()
    assert missing == 0


def test_srt_merges_cues_shorter_than_min_seconds():
    service = RENDER_MODULE.RenderService()
    # 均分后前两句各只有 0.31s：必须并成一条，不能各闪一下
    shots = [{"duration": 2.0, "dialogue": "甲。乙。丙丙丙丙丙丙丙丁？"}]
    srt, _ = service._generate_srt(shots, source="dialogue")
    assert "00:00:00,000 --> 00:00:00,615" in srt
    assert "00:00:00,615 --> 00:00:02,000" in srt
    assert "甲。乙。" in srt.splitlines()
    assert srt.count("-->") == 2

    # 镜头本身就比 0.6s 短：只能整段一条，不能编出超过镜头的时长
    short = [{"duration": 0.4, "dialogue": "甲。乙。丙。"}]
    srt, _ = service._generate_srt(short, source="dialogue")
    assert "00:00:00,000 --> 00:00:00,400" in srt
    assert srt.count("-->") == 1


def test_srt_timeline_accumulates_globally():
    service = RENDER_MODULE.RenderService()
    shots = [
        {"duration": 3.0, "dialogue": "第一句。第二句。"},
        {"duration": 3.0, "dialogue": ""},
        {"duration": 3.0, "dialogue": "第三句。"},
    ]
    # 成片真实时长优先于镜头表 duration；没有台词的镜头也照样占住它的时间
    srt, missing = service._generate_srt(
        shots, source="dialogue", durations=[1.0, 1.0, 2.0]
    )
    assert missing == 1
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:02,000 --> 00:00:04,000" in srt
    # 时间轴总长 = durations 之和，末条不能越过成片结尾
    ends = [line.split(" --> ")[1] for line in srt.splitlines() if "-->" in line]
    assert ends[-1] == "00:00:04,000"


def test_srt_wraps_long_line_into_two_lines():
    service = RENDER_MODULE.RenderService()
    text = "这是一句非常非常长的台词需要折行显示出来"  # 20 个全角字符
    srt, _ = service._generate_srt(
        [{"duration": 3.0, "dialogue": text}], source="dialogue"
    )
    lines = srt.splitlines()
    # 折行是「一条 cue 的正文换行」，不是拆成两条 cue
    assert srt.count("-->") == 1
    assert "这是一句非常非常长的" in lines
    assert "台词需要折行显示出来" in lines
    assert all(
        RENDER_MODULE._display_units(line) <= 18
        for line in lines
        if line and "-->" not in line and not line.isdigit()
    )
    # 短句不折行
    short, _ = service._generate_srt(
        [{"duration": 2.0, "dialogue": "别走。"}], source="dialogue"
    )
    assert "别走。" in short.splitlines()


def test_build_spec_subtitle_mode():
    spec, warnings = RENDER_MODULE.build_spec(
        {"resolution": "1080x1920", "aspect_ratio": "9:16"}
    )
    # 配置里没有这个键就是 hard，且不该凭空多出一条告警
    assert spec.subtitle_mode == "hard"
    assert warnings == []
    assert spec.as_dict()["subtitle_mode"] == "hard"

    for mode in ("hard", "soft", "both"):
        spec, warnings = RENDER_MODULE.build_spec({"subtitle_mode": mode})
        assert spec.subtitle_mode == mode
        assert warnings == []

    spec, warnings = RENDER_MODULE.build_spec({"subtitle_mode": "burn"})
    assert spec.subtitle_mode == "hard"
    assert any("subtitle_mode" in w for w in warnings)


@pytest.mark.asyncio
async def test_add_subtitles_dispatches_on_mode(monkeypatch, tmp_path):
    service = RENDER_MODULE.RenderService()
    video = tmp_path / "final_output.mp4"
    video.write_bytes(b"video")
    shots = [{"duration": 2.0, "dialogue": "别走。"}]
    calls = []

    async def fake_burn(src_name, srt_name, out_name, spec, workdir):
        calls.append(("burn", out_name))
        (tmp_path / out_name).write_bytes(b"hardsub")

    async def fake_mux(src_name, srt_name, out_name, workdir):
        calls.append(("mux", out_name))
        (tmp_path / out_name).write_bytes(b"soft")

    monkeypatch.setattr(service, "_burn_subtitles", fake_burn)
    monkeypatch.setattr(service, "_mux_subtitles", fake_mux)

    hard, _ = RENDER_MODULE.build_spec(
        {"subtitle_mode": "hard", "subtitle_source": "dialogue"}
    )
    out_path, srt_path, warnings = await service._add_subtitles(
        str(video), shots, None, hard
    )
    assert calls == [("burn", "final_output_subtitled.mp4")]
    assert warnings == []
    assert os.path.basename(out_path) == "final_output_subtitled.mp4"
    assert os.path.isfile(srt_path)
    with open(srt_path, encoding="utf-8") as fh:
        assert "别走。" in fh.read()

    calls.clear()
    soft, _ = RENDER_MODULE.build_spec(
        {"subtitle_mode": "soft", "subtitle_source": "dialogue"}
    )
    await service._add_subtitles(str(video), shots, None, soft)
    # soft 不重编码画面：只封软轨，绝不能顺手烧一遍
    assert calls == [("mux", "final_output_subtitled.mp4")]

    calls.clear()
    both, _ = RENDER_MODULE.build_spec(
        {"subtitle_mode": "both", "subtitle_source": "dialogue"}
    )
    await service._add_subtitles(str(video), shots, None, both)
    assert calls == [
        ("burn", "final_output_hardsub.mp4"),
        ("mux", "final_output_subtitled.mp4"),
    ]

    async def failing_mux(src_name, srt_name, out_name, workdir):
        raise RENDER_MODULE.RenderStepError("字幕软轨封装失败", "boom")

    monkeypatch.setattr(service, "_mux_subtitles", failing_mux)
    out_path, _srt, warnings = await service._add_subtitles(
        str(video), shots, None, both
    )
    # 软轨是附加能力：失败就降级成告警，成片必须还是那条硬烧好的
    assert any("软轨未封装" in w for w in warnings)
    assert os.path.basename(out_path) == "final_output_subtitled.mp4"
    assert (tmp_path / "final_output_subtitled.mp4").read_bytes() == b"hardsub"

