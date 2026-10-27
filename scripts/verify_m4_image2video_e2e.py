r"""M4-3 验收脚本：首帧图 → 图生视频（异步作业）→ 转存 → 渲染只消费产物。

与单测的区别：没有 test client、没有 eager 模式、没有 monkeypatch。
  uvicorn 子进程 ← HTTP → 提交视频作业 → filesystem broker → celery worker 子进程
  → 假 provider（本进程内的 ThreadingHTTPServer，模拟 agnes /videos 两段式）
  → 产物下载转存进本地存储 → 真 ffmpeg 渲染 → 校验成片。

用法（仓库根目录）：
    backend\venv\Scripts\python.exe scripts\verify_m4_image2video_e2e.py
    backend\venv\Scripts\python.exe scripts\verify_m4_image2video_e2e.py --live --yes-spend

两种模式：
    默认（fake）  进程内假 provider，验证管道契约，零花费，可反复跑。
    --live       打真实 provider（读 .env 的 AGNES_* 配置），**真花钱**，
                 必须显式 --yes-spend。没有 key 时直接退出 2，绝不退回 mock。

退出码 0 = 全链路通过，2 = 无 key（未取证），3 = 真实 provider 契约不符。
产物写在 backend/data/e2e_m43/（结束时保留，供复检）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
PYTHON = BACKEND / "venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
SERVER = "http://127.0.0.1:8126"
API = f"{SERVER}/api/v1"

DATA = BACKEND / "data" / "e2e_m43"
DB_PATH = DATA / "e2e.db"
UPLOADS = DATA / "e2e_uploads"
CELERY_DIR = DATA / "celery"

USERNAME = "e2e_m43_user"
PASSWORD = "e2e-Password-123"

FFMPEG = ""
PROVIDER_STATE = {"video_submits": [], "video_polls": 0, "image_calls": [], "clip": b"", "png": b""}

# --live：打真实 provider。LIVE 只影响"谁来当 provider"和"用谁的证据做断言"，
# 不改变任何业务断言——真栈上仍然是同一套检查，只是花钱。
LIVE = False
VIDEO_TIMEOUT = 180.0
LIVE_STATE = {"first_frame_ms": [], "video_job_ms": [], "download_bytes": 0}



def log(message: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"[e2e-m43] {message}", flush=True)


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, errors="ignore", **kwargs)


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        assert found, "本机没有 ffmpeg：请 pip install imageio-ffmpeg"
        return found


def read_dotenv(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        data[k.strip()] = v
    return data


def make_clip(path: Path, seconds: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=360x640:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ]
    )
    assert result.returncode == 0, result.stderr[-800:]


def make_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0x3355ff:s=512x512:d=1",
            "-frames:v", "1", str(path),
        ]
    )
    assert result.returncode == 0, result.stderr[-800:]


class FakeProvider(BaseHTTPRequestHandler):
    """假 agnes：/v1/images/generations、/v1/videos、/v1/videos/<id>、/files/<name>。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/files/out.mp4"):
            return self._bytes(PROVIDER_STATE["clip"], "video/mp4")
        if self.path.startswith("/files/frame.png"):
            return self._bytes(PROVIDER_STATE["png"], "image/png")
        if self.path.startswith("/v1/videos/"):
            task_id = self.path.rsplit("/", 1)[-1]
            PROVIDER_STATE["video_polls"] += 1
            # 第一次 processing，之后 completed —— 覆盖 worker 的真轮询循环
            if PROVIDER_STATE["video_polls"] < 2:
                return self._json({"id": task_id, "status": "processing"})
            base = f"http://127.0.0.1:{self.server.server_port}"
            return self._json(
                {
                    "id": task_id,
                    "status": "completed",
                    "video_url": f"{base}/files/out.mp4",
                    "duration": 2.0,
                }
            )
        return self._json({"error": "not found", "path": self.path}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        if self.path.startswith("/v1/videos"):
            PROVIDER_STATE["video_submits"].append(payload)
            return self._json({"id": "vjob-e2e-1", "status": "queued"}, 201)
        if self.path.startswith("/v1/images/generations"):
            PROVIDER_STATE["image_calls"].append(payload)
            base = f"http://127.0.0.1:{self.server.server_port}"
            return self._json(
                {"created": int(time.time()), "data": [{"url": f"{base}/files/frame.png"}]}
            )
        return self._json({"error": "not found", "path": self.path}, 404)


def seed_database():
    """临时库里造：用户 + 项目A（2 镜头，无素材）+ 项目B（1 镜头，无素材）。"""
    os.environ["DATABASE_PATH"] = str(DB_PATH)
    os.environ["DATABASE_TYPE"] = "sqlite"
    os.environ["STORAGE_TYPE"] = "local"
    os.environ["STORAGE_LOCAL_PATH"] = str(UPLOADS)
    os.environ.setdefault("SECRET_KEY", "e2e-m43-secret-key-0123456789abcdef012345")

    sys.path.insert(0, str(BACKEND))
    from app.core.config import settings

    assert Path(settings.DATABASE_PATH).resolve() == DB_PATH.resolve(), settings.DATABASE_PATH

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.core.security import hash_password
    from app.models import (  # noqa: F401
        ai_usage, asset, character, project, scene_asset, script, storyboard, user, video_job,
    )
    from app.models.project import Project
    from app.models.script import Scene, Script
    from app.models.storyboard import Shot, Storyboard
    from app.models.user import User

    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = str(uuid.uuid4())
    project_a = str(uuid.uuid4())
    project_b = str(uuid.uuid4())

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(
                User(
                    id=user_id, username=USERNAME, email="e2e-m43@example.com",
                    password_hash=hash_password(PASSWORD), display_name="E2E M43",
                    is_active=True, token_version=0,
                )
            )
            for pid, title, shot_count in (
                (project_a, "E2E 图生视频", 2),
                (project_b, "E2E 未绑定", 1),
            ):
                session.add(Project(id=pid, title=title, description="", owner_id=user_id, status="draft"))
                sc = Script(project_id=pid, title="第一集", content="", word_count=0)
                session.add(sc)
                await session.flush()
                session.add(
                    Scene(
                        script_id=sc.id, scene_number=1, title="雨夜街角", summary="",
                        content="", dialogue="别走。", duration=2, sort_order=0,
                    )
                )
                board = Storyboard(project_id=pid, canvas_state="{}")
                session.add(board)
                await session.flush()
                for number in range(1, shot_count + 1):
                    session.add(
                        Shot(
                            storyboard_id=board.id, shot_number=number,
                            label=f"镜头{number}", description=f"第{number}镜 雨夜街道 女孩回头",
                            duration=2.0, scene_ref="#1", sort_order=number,
                            video_prompt=f"雨夜街角，女孩回头，第{number}镜",
                        )
                    )
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())
    return project_a, project_b


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


def ops_usage(client, operation: str) -> dict:
    """从我们自己的 /ops/usage 拿真实调用证据（真 provider 模式下没有假计数器）。"""
    r = client.get("/ops/usage", params={"days": 1, "operation": operation})
    assert r.status_code == 200, f"/ops/usage 失败 {r.status_code}: {r.text[:300]}"
    return (r.json() or {}).get("total") or {}


def ops_calls(client, operation: str) -> int:
    return int(ops_usage(client, operation).get("calls") or 0)


def video_spend_count(client) -> int:
    """已发生的付费视频调用次数：假模式数假计数器，live 模式查 /ops/usage。"""
    if LIVE:
        return ops_calls(client, "video")
    return len(PROVIDER_STATE["video_submits"])


def poll_job(client, project_id: str, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        job = client.get(f"/projects/{project_id}/video-jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "timeout", "cancelled"}:
            return job
        time.sleep(2)
    raise AssertionError(f"视频作业超时未终态: {job}")


def main() -> int:
    global FFMPEG, LIVE, VIDEO_TIMEOUT

    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="打真实 provider（花费真实费用）")
    ap.add_argument("--yes-spend", action="store_true", help="确认愿意花钱（--live 必需）")
    ap.add_argument("--video-timeout", type=float, default=180.0, help="单条视频作业等待上限（秒）")
    args = ap.parse_args()

    LIVE = bool(args.live)
    VIDEO_TIMEOUT = float(args.video_timeout)

    if LIVE and not args.yes_spend:
        print("拒绝执行 --live：真实 provider 会真实计费，需要同时传 --yes-spend。")
        return 1

    FFMPEG = ffmpeg_exe()
    log(f"ffmpeg: {FFMPEG}")

    if DATA.exists():
        shutil.rmtree(DATA)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    CELERY_DIR.mkdir(parents=True, exist_ok=True)

    live_env = {}
    if LIVE:
        live_env = read_dotenv(REPO_ROOT / ".env")
        key = (live_env.get("AGNES_API_KEY") or os.environ.get("AGNES_API_KEY") or "").strip()
        if not key:
            print("=" * 72)
            print("BLOCKED：AGNES_API_KEY 为空，--live 无法取证。")
            print("把 key 写进仓库根 .env 的 AGNES_API_KEY= 之后重跑；")
            print("本脚本不会退回假 provider 来假装打通。")
            print("=" * 72)
            return 2
        log(f"真实 provider 模式：base={live_env.get('AGNES_API_BASE', '(默认)')} key={key[:4]}***")

    clip = DATA / "provider_clip.mp4"
    png = DATA / "provider_frame.png"
    make_clip(clip, seconds=2.0)
    make_png(png)
    PROVIDER_STATE["clip"] = clip.read_bytes()
    PROVIDER_STATE["png"] = png.read_bytes()

    class QuietServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # 收尾阶段客户端断开（uvicorn/httpx 先退出）会抛 ConnectionResetError，
            # 那只是测试脚本自己的噪声，不该污染验收日志。
            import sys as _sys

            exc = _sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    provider = None
    provider_port = 0
    if not LIVE:
        provider = QuietServer(("127.0.0.1", 0), FakeProvider)
        provider_port = provider.server_port
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        log(f"假 provider 起在 127.0.0.1:{provider_port}")

    project_a, project_b = seed_database()
    log(f"已造项目 A={project_a} B={project_b}")

    image_chain = json.dumps(
        [{"name": "agnes", "base": f"http://127.0.0.1:{provider_port}/v1",
          "model": "fake-image", "api_key": "test-key"}]
    )
    video_chain = json.dumps(
        [{"name": "agnes", "base": f"http://127.0.0.1:{provider_port}/v1",
          "model": "fake-video", "api_key": "test-key"}]
    )

    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(BACKEND),
            "SECRET_KEY": "e2e-m43-secret-key-0123456789abcdef012345",
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
            "AI_MOCK_ENABLED": "false",
            "RENDER_ALLOW_INLINE_VIDEO": "false",
            "AI_DAILY_QUOTA": "100",
        }
    )
    if LIVE:
        # 关键：live 模式**不覆盖** provider 链，让 config.py 用 .env 的 AGNES_* 自己拼；
        # 只把 key/base/model 显式注入子进程（环境变量优先级高于 .env 文件）。
        env.update({k: v for k, v in live_env.items() if k.startswith("AGNES_")})
        env.pop("AI_IMAGE_PROVIDERS_RAW", None)
        env.pop("AI_VIDEO_PROVIDERS_RAW", None)
    else:
        env["AI_IMAGE_PROVIDERS_RAW"] = image_chain
        env["AI_VIDEO_PROVIDERS_RAW"] = video_chain

    server = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8126"],
        cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    worker_log = DATA / "worker.log"
    worker = subprocess.Popen(
        [str(PYTHON), "-m", "celery", "-A", "app.tasks.celery_app.celery_app",
         "worker", "-P", "solo", "-l", "warning", "--without-gossip", "--without-mingle"],
        cwd=str(BACKEND), env=env,
        stdout=worker_log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
    )

    try:
        import httpx

        wait_http(f"{API}/health")
        log("API 就绪")
        time.sleep(6)  # worker 导入 app 需要几秒

        with httpx.Client(base_url=API, timeout=60, follow_redirects=True) as client:
            response = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
            assert response.status_code == 200, f"登录失败 {response.status_code}: {response.text[:400]}"
            log("登录成功")

            board = client.get(f"/projects/{project_a}/storyboard").json()
            shots = board["shots"] if isinstance(board, dict) else board
            shot_ids = [s["id"] for s in shots]
            assert len(shot_ids) == 2, f"镜头数不符: {len(shot_ids)}"

            # ---- 1. 出首帧（真 provider → 转存 → 镜头落 image_url）----
            frames = []
            t_frames = time.time()
            for shot_id in shot_ids:
                frame = client.post(
                    f"/projects/{project_a}/storyboard/shots/{shot_id}/first-frame", json={}
                )
                assert frame.status_code == 200, f"出首帧失败 {frame.status_code}: {frame.text[:600]}"
                body = frame.json()
                assert body.get("image_url"), f"首帧响应缺 image_url: {body}"
                frames.append(body["image_url"])
            if LIVE:
                calls = ops_calls(client, "image")
                assert calls >= 2, f"/ops/usage 只记到 {calls} 次 image 调用，少于 2 次"
                log(f"真实出图调用已记账 {calls} 次（ops/usage） [OK]")
            else:
                assert len(PROVIDER_STATE["image_calls"]) == 2, (
                    f"应当调用两次图片 provider，实际 {len(PROVIDER_STATE['image_calls'])}"
                )
            LIVE_STATE["first_frame_ms"].append(int((time.time() - t_frames) * 1000))
            log(f"两镜首帧已生成并落库: {frames[0][:60]}...")

            # 首帧必须真的进了本地存储（不是第三方临时链接）
            for frame_url in frames:
                name = frame_url.split("?")[0].split("/uploads/")[-1]
                assert (UPLOADS / name).exists(), f"首帧未落本地存储: {name}"
            log("首帧已转存本地（非第三方临时链接） [OK]")

            # ---- 2. 图生视频：异步作业跑完 → 转存 → 回填镜头 ----
            for shot_id in shot_ids:
                created = client.post(
                    f"/projects/{project_a}/shots/{shot_id}/video-jobs",
                    json={"duration": 5},
                )
                assert created.status_code == 201, f"提交视频作业失败 {created.status_code}: {created.text[:600]}"
                job = created.json()
                log(f"作业已提交 {job['id']} status={job['status']}")
                t_job = time.time()
                finished = poll_job(client, project_a, job["id"], timeout=VIDEO_TIMEOUT)
                LIVE_STATE["video_job_ms"].append(int((time.time() - t_job) * 1000))
                assert finished["status"] == "completed", f"作业未完成: {finished}"
                assert finished["video_url"], f"作业 completed 但无 video_url: {finished}"
                assert not finished["warnings"], f"作业有告警（转存降级？）: {finished['warnings']}"
                log(f"作业完成: {finished['video_url'][:60]}...")

            if LIVE:
                usage = ops_usage(client, "video")
                assert int(usage.get("calls") or 0) >= 2, f"视频调用未记账: {usage}"
                assert int(usage.get("success") or 0) >= 2, f"有视频调用未成功: {usage}"
                log(f"真实视频调用已记账 {usage.get('calls')} 次 / success={usage.get('success')} [OK]")
                log("注意：首帧图是否被 provider 真正采纳，本脚本无法证明——")
                log("     必须另跑 scripts/m4_live_probe.py --shots s3 --image-mode <形态> 并人眼比对首帧。")
            else:
                submits = PROVIDER_STATE["video_submits"]
                assert len(submits) == 2, f"视频 provider 应被调用 2 次，实际 {len(submits)}"
                for payload in submits:
                    assert payload.get("image"), f"图生视频必须带 image 入参，实际 payload={payload}"
                    assert payload.get("num_frames") == 121, f"5s 应对应 121 帧，实际 {payload.get('num_frames')}"
                log("每次提交都带首帧图 + 121 帧（真图生视频） [OK]")

            # 镜头回填：GET 镜头应能看到 signing 过的 video_url
            board2 = client.get(f"/projects/{project_a}/storyboard").json()
            shots2 = board2["shots"] if isinstance(board2, dict) else board2
            for shot in shots2:
                assert shot.get("video_url"), f"镜头 {shot['id']} 未回填 video_url"
                assert "sig=" in shot["video_url"], f"镜头视频 URL 未签名: {shot['video_url']}"
            log("两镜 video_url 已回填并签名 [OK]")

            # ---- 3. 渲染只消费产物：不得再调用付费视频生成 ----
            before = video_spend_count(client)
            config = {
                "resolution": "1080x1920", "aspect_ratio": "9:16", "fps": 24, "quality": "low",
                "visual_style": "写实", "add_subtitles": True, "subtitle_source": "dialogue",
                "add_bgm": False,
            }
            payload = {"name": "E2E M43 成片", "config": config, "idempotency_key": str(uuid.uuid4())}
            submit = client.post(f"/projects/{project_a}/render", json=payload)
            assert submit.status_code == 201, f"提交渲染失败 {submit.status_code}: {submit.text[:600]}"
            task_id = submit.json()["id"]
            deadline = time.time() + 240
            status = {}
            while time.time() < deadline:
                status = client.get(f"/render/{task_id}/status").json()
                if status["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            assert status.get("status") == "completed", f"渲染失败: {status.get('error_message')}"
            assert video_spend_count(client) == before, (
                "渲染期间又调用了付费视频生成（RENDER_ALLOW_INLINE_VIDEO 没生效）"
            )
            log("渲染完成，且未再调用视频 provider [OK]")

            download = client.get(f"/render/{task_id}/download")
            assert download.status_code == 200, download.text[:400]
            url = download.json()["download_url"]
            assert "sig=" in url, f"下载 URL 必须签名: {url}"
            media = httpx.get(f"{SERVER}{url}", timeout=120)
            assert media.status_code == 200, f"签名下载失败 {media.status_code}"
            output = DATA / "output.mp4"
            output.write_bytes(media.content)
            assert output.stat().st_size > 10_000, "成片过小"
            LIVE_STATE["download_bytes"] = output.stat().st_size
            probe = run([FFMPEG, "-hide_banner", "-i", str(output)]).stderr
            assert "1080x1920" in probe, f"分辨率不符: {probe[-400:]}"
            assert "Audio:" in probe, "成片没有音轨"
            log(f"成片校验通过: {output.stat().st_size} bytes, 1080x1920, 带音轨")

            # ---- 4. 未绑定素材的镜头：渲染必须报可操作错误，而不是偷偷扣费 ----
            before = video_spend_count(client)
            payload_b = {"name": "E2E 未绑定", "config": config, "idempotency_key": str(uuid.uuid4())}
            submit_b = client.post(f"/projects/{project_b}/render", json=payload_b)
            assert submit_b.status_code == 201, submit_b.text[:400]
            task_b = submit_b.json()["id"]
            deadline = time.time() + 120
            status_b = {}
            while time.time() < deadline:
                status_b = client.get(f"/render/{task_b}/status").json()
                if status_b["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            assert status_b.get("status") == "failed", f"未绑定镜头应渲染失败: {status_b}"
            message = status_b.get("error_message") or ""
            assert "未绑定素材" in message or "先绑定素材" in message or "生成视频" in message, (
                f"错误信息不可操作: {message}"
            )
            assert video_spend_count(client) == before, (
                "未绑定素材时不应内联调用付费视频生成"
            )
            log(f"未绑定镜头报可操作错误且未扣费 [OK] -> {message[:80]}")

            worker_text = worker_log.read_text(encoding="utf-8", errors="ignore") if worker_log.exists() else ""
            assert "Traceback" not in worker_text, "worker 日志出现 Traceback（见 backend/data/e2e_m43/worker.log）"
            log("worker 日志无 Traceback [OK]")

            if LIVE:
                summary = {
                    "mode": "live",
                    "base": live_env.get("AGNES_API_BASE", ""),
                    "first_frame_ms": LIVE_STATE["first_frame_ms"],
                    "video_job_ms": LIVE_STATE["video_job_ms"],
                    "output_bytes": LIVE_STATE["download_bytes"],
                    "usage_image": ops_usage(client, "image"),
                    "usage_video": ops_usage(client, "video"),
                    "note": "estimated_cost_usd 用的是占位单价，真实账单只能以供应商后台为准",
                }
                path = DATA / "live_summary.json"
                path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                log(f"真实链路实测：首帧 {summary['first_frame_ms']} ms，"
                    f"单条视频作业 {summary['video_job_ms']} ms，成片 {summary['output_bytes']} bytes")
                log(f"用量明细 -> {path}")
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
        if provider is not None:
            provider.shutdown()
        log("已停止子进程（数据保留在 backend/data/e2e_m43/）")


if __name__ == "__main__":
    sys.exit(main())
