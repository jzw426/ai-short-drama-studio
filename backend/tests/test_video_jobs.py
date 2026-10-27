"""M4-3 AI 视频作业：提交 → 轮询 → 转存 → 回填 → 取消 的端到端单测。

用 ThreadingHTTPServer 扮一个真视频 provider（POST /v1/videos 提交、
GET /v1/videos/{id} 轮询、外加一个能真下载的 mp4 端点），所以提交、轮询、转存
三条链路都是真跑的（真 HTTP、真落盘），只有 Celery 的入队入口被替换成 no-op
——测试直接调 advance_video_job，不依赖 broker/worker。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import video_jobs as video_jobs_route
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.project import Project
from app.models.storyboard import Shot, Storyboard
from app.models.video_job import AIVideoJob
from app.services.ai_service import VideoCapabilityError, ai_service
from app.tasks import video_job_task

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42-fake-video-bytes"

# 假 provider 的共享状态：断言 provider 到底收到了什么
PROVIDER = {
    "submits": [],        # 每次 POST /videos 的 {payload, authorization, path}
    "polls": 0,           # GET /videos/{id} 次数
    "mode": "ok",         # ok | no_image（收到 image 就 400，模拟不支持图生视频）
    "complete_after": 2,  # 第几次轮询返回 completed
    "video_url": "",      # provider 的回片地址
}


class FakeVideoProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 测试输出保持干净
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.endswith("/videos"):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
            PROVIDER["submits"].append(
                {
                    "payload": payload,
                    "authorization": self.headers.get("Authorization"),
                    "path": self.path,
                }
            )
            if PROVIDER["mode"] == "no_image" and "image" in payload:
                # 真实 provider 拒绝图生视频时的典型响应
                self._send_json({"error": "image input is not supported"}, status=400)
                return
            self._send_json({"id": "task-1", "status": "queued"})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_GET(self):
        if self.path.startswith("/media/"):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(MP4_BYTES)))
            self.end_headers()
            self.wfile.write(MP4_BYTES)
            return
        if "/videos/task-1" in self.path:
            PROVIDER["polls"] += 1
            if PROVIDER["polls"] < PROVIDER["complete_after"]:
                self._send_json({"id": "task-1", "status": "processing"})
            else:
                self._send_json(
                    {
                        "id": "task-1",
                        "status": "completed",
                        "video_url": PROVIDER["video_url"],
                    }
                )
            return
        self._send_json({"error": "not found"}, status=404)


@pytest.fixture
def provider(monkeypatch):
    """起一个本地假视频 provider，并把视频 provider 链指向它。"""
    PROVIDER.update(
        {"submits": [], "polls": 0, "mode": "ok", "complete_after": 2}
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVideoProvider)
    host, port = server.server_address
    PROVIDER["video_url"] = f"http://{host}:{port}/media/video-1.mp4"
    base = f"http://{host}:{port}/v1"

    monkeypatch.setattr(
        settings,
        "AI_VIDEO_PROVIDERS_RAW",
        json.dumps(
            [{"name": "agnes", "base": base, "model": "fake-video", "api_key": "k"}]
        ),
    )
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    # 上一个用例的失败计数可能让 provider 处于冷却期（模块级单例），先清零
    ai_service._report_success("video", "agnes")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest_asyncio.fixture
async def ctx(tmp_path, monkeypatch):
    """内存库 + 两个项目（本人/他人）+ 两个镜头 + 直接挂 router 的 app。"""
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path / "uploads"))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with maker() as session:
        session.add(Project(id="proj-1", title="我的项目", owner_id="user-1"))
        session.add(Project(id="proj-2", title="别人的项目", owner_id="user-2"))
        session.add(Storyboard(id="sb-1", project_id="proj-1", canvas_state="{}"))
        session.add(
            Shot(
                id="shot-1",
                storyboard_id="sb-1",
                shot_number=1,
                label="镜头1",
                description="雨夜街头",
                video_prompt="赛博朋克雨夜街头，霓虹灯反射",
                image_url="/uploads/ai/images/frame-1.png",
                duration=5.0,
            )
        )
        session.add(
            Shot(
                id="shot-2",
                storyboard_id="sb-1",
                shot_number=2,
                label="镜头2",
                description="第二个镜头",
                video_url="/uploads/manual/keep.mp4",
            )
        )
        await session.commit()

    app = FastAPI()
    app.include_router(video_jobs_route.router, prefix="/api/v1")

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", username="tester"
    )

    # 作业推进用测试库；AI 用量记账也写测试库（不碰生产库）
    monkeypatch.setattr(video_job_task, "_session_factory", maker)
    monkeypatch.setattr(ai_service, "usage_session_factory", maker)
    # 入队：测试里绝不触发真实 broker/worker，由用例自己调 advance_video_job
    monkeypatch.setattr(video_jobs_route, "enqueue_video_job", lambda job_id: None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, maker=maker, app=app, tmp_path=tmp_path
        )
    await engine.dispose()


async def _create_job(client, shot_id="shot-1", project_id="proj-1", **body):
    return await client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/video-jobs", json=body
    )


async def _load_job(ctx, job_id: str) -> AIVideoJob:
    async with ctx.maker() as session:
        return await session.get(AIVideoJob, job_id)


async def _load_shot(ctx, shot_id: str) -> Shot:
    async with ctx.maker() as session:
        return await session.get(Shot, shot_id)


@pytest.mark.asyncio
async def test_submit_poll_complete_and_backfill(ctx, provider):
    resp = await _create_job(ctx.client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["id"]
    # 提示词/首帧图都从镜头继承，不用前端重复传
    assert body["status"] == "pending"
    assert body["prompt"] == "赛博朋克雨夜街头，霓虹灯反射"
    assert body["image_url"] == "/uploads/ai/images/frame-1.png"
    assert body["provider"] == ""

    # ① 第一次推进 = 提交：payload 必须带 image（图生视频），帧数按时长换算
    assert await video_job_task.advance_video_job(job_id) == "processing"
    job = await _load_job(ctx, job_id)
    assert job.status == "submitted"
    assert job.provider == "agnes" and job.model == "fake-video"
    assert job.provider_task_id == "task-1"
    assert job.poll_count == 0
    assert job.next_poll_at is not None

    assert len(PROVIDER["submits"]) == 1
    sent = PROVIDER["submits"][0]
    assert sent["path"].endswith("/videos")
    assert sent["payload"]["model"] == "fake-video"
    assert sent["payload"]["num_frames"] == 121  # 5s → 8n+1
    assert sent["payload"]["frame_rate"] == 24
    assert sent["payload"]["prompt"] == "赛博朋克雨夜街头，霓虹灯反射"
    # local 存储没有公网 base URL：退回库里的规范地址，但绝不丢图
    assert sent["payload"]["image"] == "/uploads/ai/images/frame-1.png"
    assert sent["authorization"] == "Bearer k"

    # ② 第二轮仍是 processing
    assert await video_job_task.advance_video_job(job_id) == "processing"
    job = await _load_job(ctx, job_id)
    assert job.status == "polling"
    assert job.poll_count == 1
    assert job.video_url is None

    # ③ 第三轮 completed：转存进自有存储 + 回填镜头
    assert await video_job_task.advance_video_job(job_id) == "completed"
    job = await _load_job(ctx, job_id)
    assert job.status == "completed"
    assert job.error is None
    assert job.video_url.startswith("/uploads/ai/videos/proj-1/")
    assert job.video_url.endswith(".mp4")

    stored = list((ctx.tmp_path / "uploads" / "ai" / "videos" / "proj-1").glob("*.mp4"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == MP4_BYTES

    shot = await _load_shot(ctx, "shot-1")
    assert shot.video_url == job.video_url

    # 终态不再推进（幂等，不会重复花一次 AI 钱）
    assert await video_job_task.advance_video_job(job_id) == "skipped"
    assert PROVIDER["polls"] == 2


@pytest.mark.asyncio
async def test_completed_does_not_overwrite_bound_shot_video(ctx, provider):
    resp = await _create_job(ctx.client, shot_id="shot-2", prompt="自定义提示词")
    assert resp.status_code == 201, resp.text
    assert resp.json()["prompt"] == "自定义提示词"
    job_id = resp.json()["id"]

    assert await video_job_task.advance_video_job(job_id) == "processing"
    assert await video_job_task.advance_video_job(job_id) == "processing"
    assert await video_job_task.advance_video_job(job_id) == "completed"

    # 人工绑定的素材优先：作业完成也绝不覆盖
    shot = await _load_shot(ctx, "shot-2")
    assert shot.video_url == "/uploads/manual/keep.mp4"


@pytest.mark.asyncio
async def test_provider_rejects_image_keeps_failure(ctx, provider):
    PROVIDER["mode"] = "no_image"
    resp = await _create_job(ctx.client)
    job_id = resp.json()["id"]

    assert await video_job_task.advance_video_job(job_id) == "failed"
    job = await _load_job(ctx, job_id)
    assert job.status == "failed"
    assert job.status != "completed"
    assert "首帧图" in (job.error or "")
    # 报错而不是静默去掉 image 重试：provider 确实收到了 image
    assert "image" in PROVIDER["submits"][-1]["payload"]


@pytest.mark.asyncio
async def test_submit_video_raises_capability_error(ctx, provider):
    PROVIDER["mode"] = "no_image"
    with pytest.raises(VideoCapabilityError):
        await ai_service.submit_video(
            "测试提示词", image_url="/uploads/ai/images/frame-1.png"
        )


@pytest.mark.asyncio
async def test_cancel_stops_further_advance(ctx, provider):
    resp = await _create_job(ctx.client)
    job_id = resp.json()["id"]

    cancel = await ctx.client.post(
        f"/api/v1/projects/proj-1/video-jobs/{job_id}/cancel"
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    # 取消后 worker 再推进也不会把状态改回去、更不会去花钱提交
    assert await video_job_task.advance_video_job(job_id) == "skipped"
    assert (await _load_job(ctx, job_id)).status == "cancelled"
    assert PROVIDER["submits"] == []

    # 已经是终态：重复取消 400
    again = await ctx.client.post(
        f"/api/v1/projects/proj-1/video-jobs/{job_id}/cancel"
    )
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_list_jobs_filter_and_order(ctx, provider):
    first = (await _create_job(ctx.client, shot_id="shot-1")).json()["id"]
    second = (await _create_job(ctx.client, shot_id="shot-2")).json()["id"]
    await ctx.client.post(f"/api/v1/projects/proj-1/video-jobs/{first}/cancel")

    listed = await ctx.client.get("/api/v1/projects/proj-1/video-jobs")
    assert listed.status_code == 200, listed.text
    ids = [item["id"] for item in listed.json()]
    # 新的在前
    assert ids.index(second) < ids.index(first)

    only_cancelled = await ctx.client.get(
        "/api/v1/projects/proj-1/video-jobs", params={"status": "cancelled"}
    )
    assert [item["id"] for item in only_cancelled.json()] == [first]

    single = await ctx.client.get(f"/api/v1/projects/proj-1/video-jobs/{second}")
    assert single.status_code == 200
    assert single.json()["id"] == second


@pytest.mark.asyncio
async def test_router_requires_auth_and_ownership(ctx, provider):
    # 未登录 → 401
    saved = ctx.app.dependency_overrides.pop(get_current_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=ctx.app), base_url="http://test"
        ) as anon:
            unauthorized = await anon.get("/api/v1/projects/proj-1/video-jobs")
        assert unauthorized.status_code == 401
    finally:
        ctx.app.dependency_overrides[get_current_user] = saved

    # 别人的项目 → 404（不泄露存在性）
    other = await _create_job(ctx.client, project_id="proj-2")
    assert other.status_code == 404

    # 不存在的作业 → 404
    missing = await ctx.client.get("/api/v1/projects/proj-1/video-jobs/no-such-job")
    assert missing.status_code == 404

    # 不存在的作业直接推进 → skipped，不抛错
    assert await video_job_task.advance_video_job("no-such-job") == "skipped"
