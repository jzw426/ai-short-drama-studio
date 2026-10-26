"""Celery 任务层的真实闭环：任务被真的执行、状态真的落库。

这里用 `task_always_eager=True` 把 worker 逻辑跑在当前进程里（本机没有
Redis，eager 是唯一能不经 broker 验证任务体的方式；broker 级验证见
scripts/verify_render_worker.py）。断言的是"任务跑完后库里的 RenderTask
到底是什么状态"——而不是"函数有没有被调用"。
"""
from __future__ import annotations

import asyncio
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

pytestmark = pytest.mark.skipif(not FFMPEG, reason="本机没有 ffmpeg，跳过任务闭环测试")


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
