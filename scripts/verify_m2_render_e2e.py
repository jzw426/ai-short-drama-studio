r"""M2 验收脚本：真实 API + 真实 Celery worker + 真实 FFmpeg → 真成片。

与其他测试的区别：这里没有 test client、没有 eager 模式、没有 monkeypatch：
  uvicorn 子进程 ← HTTP → 提交任务 → filesystem broker → celery worker 子进程
  → 真 ffmpeg 合成 → 本地存储 → 带签名的下载 URL → 校验成片分辨率/大小。

用法（在仓库根目录）：
    backend\venv\Scripts\python.exe scripts\verify_m2_render_e2e.py

退出码 0 = 全链路通过；非 0 = 失败并打印原因。
产物写在 backend/data/e2e/（脚本结束会清理数据库与上传目录）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
PYTHON = BACKEND / "venv" / "Scripts" / "python.exe"
if not PYTHON.exists():  # 非 Windows / 未建 venv
    PYTHON = Path(sys.executable)
SERVER = "http://127.0.0.1:8124"
API = f"{SERVER}/api/v1"

DATA = BACKEND / "data" / "e2e"
DB_PATH = DATA / "e2e.db"
UPLOADS = DATA / "e2e_uploads"
CELERY_DIR = DATA / "celery"

USERNAME = "e2e_user"
PASSWORD = "e2e-Password-123"


def log(message: str) -> None:
    # Windows 控制台默认 GBK，直接 print 中文/符号会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"[e2e] {message}", flush=True)


def run(cmd: list[str], **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, errors="ignore", **kwargs)


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        assert found, "本机没有 ffmpeg：请 pip install imageio-ffmpeg 或安装系统 ffmpeg"
        return found


def make_clip(path: Path, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ]
    )
    assert result.returncode == 0, result.stderr[-800:]


def probe(path: Path) -> str:
    return run([FFMPEG, "-hide_banner", "-i", str(path)]).stderr


def seed_database() -> tuple[str, str, str]:
    """直接在临时库里造一个用户 + 项目 + 两个已绑定素材的镜头。"""
    os.environ["DATABASE_PATH"] = str(DB_PATH)
    os.environ["DATABASE_TYPE"] = "sqlite"
    os.environ["STORAGE_TYPE"] = "local"
    os.environ["STORAGE_LOCAL_PATH"] = str(UPLOADS)
    os.environ["CELERY_BROKER_URL"] = "filesystem://"
    os.environ["CELERY_FILESYSTEM_DIR"] = str(CELERY_DIR)
    os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
    os.environ["FFMPEG_PATH"] = FFMPEG
    os.environ.setdefault("SECRET_KEY", "e2e-secret-key-0123456789abcdef0123456789abcdef")

    sys.path.insert(0, str(BACKEND))
    from app.core.config import settings  # noqa: WPS433 - 必须在 env 之后导入

    assert Path(settings.DATABASE_PATH).resolve() == DB_PATH.resolve(), settings.DATABASE_PATH

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.core.security import hash_password
    from app.models import asset, ai_usage, character, project, script, storyboard, user  # noqa: F401
    from app.models.project import Project
    from app.models.script import Scene, Script
    from app.models.storyboard import Shot, Storyboard
    from app.models.user import User

    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    project_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    username=USERNAME,
                    email="e2e@example.com",
                    password_hash=hash_password(PASSWORD),
                    display_name="E2E",
                    is_active=True,
                    token_version=0,
                )
            )
            session.add(
                Project(
                    id=project_id,
                    title="E2E 雨夜",
                    description="",
                    owner_id=user_id,
                    status="draft",
                )
            )
            # 剧本 + 场景台词：用来验证 subtitle_source="dialogue" 真的走了台词，
            # 而不是悄悄回退到画面描述（回退会在 worker 日志里留"没有台词"）。
            script = Script(project_id=project_id, title="第一集", content="", word_count=0)
            session.add(script)
            await session.flush()
            session.add(
                Scene(
                    script_id=script.id,
                    scene_number=1,
                    title="雨夜街角",
                    summary="",
                    content="",
                    dialogue="别走。",
                    duration=2,
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
                        duration=1.0,
                        scene_ref="#1",
                        video_url=f"/uploads/segments/seg{number}.mp4",
                        sort_order=number,
                    )
                )
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())
    return project_id, user_id, ""


def wait_http(url: str, timeout: float = 60.0) -> None:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"服务未就绪: {url}")


def main() -> int:
    global FFMPEG
    FFMPEG = ffmpeg_exe()
    log(f"ffmpeg: {FFMPEG}")

    if DATA.exists():
        shutil.rmtree(DATA)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    CELERY_DIR.mkdir(parents=True, exist_ok=True)

    project_id, _, _ = seed_database()
    for number in (1, 2):
        make_clip(UPLOADS / "segments" / f"seg{number}.mp4", seconds=1.0)
    log(f"已造项目 {project_id}")

    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(BACKEND),
            "SECRET_KEY": "e2e-secret-key-0123456789abcdef0123456789abcdef",
            "ENVIRONMENT": "development",
            "DATABASE_TYPE": "sqlite",
            "DATABASE_PATH": str(DB_PATH),
            "STORAGE_TYPE": "local",
            "STORAGE_LOCAL_PATH": str(UPLOADS),
            "CELERY_BROKER_URL": "filesystem://",
            "CELERY_FILESYSTEM_DIR": str(CELERY_DIR),
            "CELERY_RESULT_BACKEND": "cache+memory://",
            "FFMPEG_PATH": FFMPEG,
            "LOG_LEVEL": "WARNING",
            "LOG_FORMAT": "plain",
        }
    )

    server = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8124"],
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker_log = DATA / "worker.log"
    worker = subprocess.Popen(
        [
            str(PYTHON), "-m", "celery", "-A", "app.tasks.celery_app.celery_app",
            "worker", "-P", "solo", "-l", "warning",
            "--without-gossip", "--without-mingle",
        ],
        cwd=str(BACKEND),
        env=env,
        stdout=worker_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )

    try:
        import httpx

        wait_http(f"{API}/health")
        log("API 就绪")

        with httpx.Client(base_url=API, timeout=60, follow_redirects=True) as client:
            response = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
            assert response.status_code == 200, f"登录失败 {response.status_code}: {response.text[:400]}"
            log("登录成功（拿到 httpOnly Cookie）")

            # worker 起来需要几秒（导入 app + 建 broker 目录）
            time.sleep(6)

            config = {
                "resolution": "1080x1920",
                "aspect_ratio": "9:16",
                "fps": 24,
                "quality": "low",
                "visual_style": "写实",
                "add_subtitles": True,
                "subtitle_source": "dialogue",
                "add_bgm": False,
            }
            idem = str(uuid.uuid4())
            payload = {"name": "E2E 成片", "config": config, "idempotency_key": idem}
            submit = client.post(f"/projects/{project_id}/render", json=payload)
            assert submit.status_code == 201, f"提交失败 {submit.status_code}: {submit.text[:600]}"
            task_id = submit.json()["id"]
            log(f"提交成功 task={task_id}")

            again = client.post(f"/projects/{project_id}/render", json=payload)
            assert again.status_code == 200 and again.json()["id"] == task_id, (
                f"幂等提交应返回同一任务，实际 {again.status_code}: {again.text[:300]}"
            )
            log("幂等提交返回同一任务 [OK]")

            deadline = time.time() + 180
            status = {}
            while time.time() < deadline:
                status = client.get(f"/render/{task_id}/status").json()
                if status["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            log(f"任务终态: {status.get('status')} progress={status.get('progress')}")
            assert status.get("status") == "completed", f"渲染失败: {status.get('error_message')}"

            download = client.get(f"/render/{task_id}/download")
            assert download.status_code == 200, download.text[:400]
            download_url = download.json()["download_url"]
            # 本地模式签名参数是 ?exp=&sig=（见 backend/app/core/media_urls.py）
            assert "sig=" in download_url and "exp=" in download_url, (
                f"下载 URL 必须带签名（私有存储），实际: {download_url}"
            )

            media = httpx.get(f"{SERVER}{download_url}", timeout=60)
            assert media.status_code == 200, f"签名下载失败 {media.status_code}"
            output_path = DATA / "output.mp4"
            output_path.write_bytes(media.content)
            assert output_path.stat().st_size > 10_000, "成片过小"

            anonymous = httpx.get(f"{SERVER}{download_url.split('?')[0]}", timeout=30)
            assert anonymous.status_code == 401, (
                f"去掉签名后应 401（私有媒体），实际 {anonymous.status_code}"
            )
            log("匿名访问成片被拒 [OK]")

            # 台词必须真的进了字幕：回退到画面描述会在 worker 日志留"没有台词"
            worker_text = (
                worker_log.read_text(encoding="utf-8", errors="ignore")
                if worker_log.exists()
                else ""
            )
            assert "没有台词" not in worker_text, (
                "subtitle_source=dialogue 但字幕回退到了画面描述（见 worker.log）"
            )
            assert "Traceback" not in worker_text, "worker 日志出现 Traceback（见 backend/data/e2e/worker.log）"
            log("字幕取到剧本台词（无回退） [OK]")

            info = probe(output_path)
            assert "1080x1920" in info, f"成片分辨率不符: {info[-500:]}"
            assert "Audio:" in info, "成片没有音轨"
            log(f"成片校验通过: {output_path.stat().st_size} bytes, 1080x1920, 带音轨")
            return 0
    finally:
        for process in (worker, server):
            if process.poll() is None:
                process.terminate()
        for process in (worker, server):
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        if worker_log.exists():
            tail = worker_log.read_text(encoding="utf-8", errors="ignore")[-2000:]
            if "Traceback" in tail:
                log("worker 日志里出现 Traceback（见 backend/data/e2e/worker.log）")
        log("已停止子进程（临时数据保留在 backend/data/e2e/ 供复检）")


if __name__ == "__main__":
    sys.exit(main())
