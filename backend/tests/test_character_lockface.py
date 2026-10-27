"""M4-2 角色一致性：锁脸（角色卡）、种子、三视图、provider 能力失败语义。

覆盖：
- 未锁脸：文生图 → 成功即自动锁脸（基准图 + 种子 + 外观描述落库）
- 锁脸：基准图转存到自有存储，seed 固化，不调用 AI、不占配额
- 已锁脸：出图走 /images/edits（参考图 + seed 透传），绝不再走文生图
- provider 不支持 edits：501 + 配额退回（不能静默换一张脸，也不能白扣次数）
- 三视图：未锁脸 400；锁脸后逐视角生成并写入 view_images
"""
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - 注册全部模型
from app.api.routes import characters as characters_route
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.character import Character
from app.models.project import Project

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\x0d\x0a-\xb4\x00\x00\x00\x00IEND\xaeB\x60\x82"
)

CALLS: list = []


class FakeProvider(BaseHTTPRequestHandler):
    """冒充 OpenAI 兼容图片服务：generations / edits / 文件下载。

    edits 用小状态码模拟"这个 provider 没有图生图能力"。
    """

    edits_status = 200

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _base(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        path = self.path.split("?")[0]
        if path.endswith("/images/generations"):
            payload = json.loads(body.decode() or "{}")
            CALLS.append(("generations", payload))
            self._send_json({"data": [{"url": f"{self._base()}/files/gen{len(CALLS)}.png"}]})
            return
        if path.endswith("/images/edits"):
            CALLS.append(
                ("edits", body, self.headers.get("content-type", ""), self.headers.get("authorization", ""))
            )
            if FakeProvider.edits_status != 200:
                self.send_error(FakeProvider.edits_status)
                return
            self._send_json({"data": [{"url": f"{self._base()}/files/edit{len(CALLS)}.png"}]})
            return
        self.send_error(404)

    def do_GET(self):  # noqa: N802
        if "/files/" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_BYTES)))
            self.end_headers()
            self.wfile.write(PNG_BYTES)
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture
def provider(monkeypatch):
    CALLS.clear()
    FakeProvider.edits_status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}/v1"
    monkeypatch.setattr(
        settings,
        "AI_IMAGE_PROVIDERS_RAW",
        json.dumps([{"name": "agnes", "base": base, "model": "fake-image", "api_key": "k"}]),
    )
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    try:
        yield SimpleNamespace(base=base, calls=CALLS, server=server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest_asyncio.fixture
async def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 100)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    project_id = str(uuid.uuid4())
    async with maker() as session:
        session.add(Project(id=project_id, title="p", owner_id="u1"))
        await session.commit()

    app = FastAPI()
    app.include_router(characters_route.router, prefix="/api/v1")

    async def _override_db():
        # 生产语义：请求结束统一提交（get_db 负责事务边界）。不提交的话
        # 上一步 lock-face 写的基准图对下一个请求不可见。
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user():
        return SimpleNamespace(id="u1")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    # 记账用测试库会话工厂，否则会往真实开发库写（表不存在 → 只 warning，噪音大）
    from app.services.ai_service import ai_service

    monkeypatch.setattr(ai_service, "usage_session_factory", maker)

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        yield SimpleNamespace(
            client=client, maker=maker, project_id=project_id, root=tmp_path / "uploads"
        )
    finally:
        await client.aclose()
        await engine.dispose()


async def _create_character(ctx, **kwargs) -> str:
    async with ctx.maker() as session:
        character = Character(
            project_id=ctx.project_id,
            name="林夜",
            gender="female",
            age=24,
            traits=["冷静", "毒舌"],
            description="黑长直，红风衣，左手有疤",
            **kwargs,
        )
        session.add(character)
        await session.commit()
        return character.id


# ==================== 文生图 → 自动锁脸 ====================


@pytest.mark.asyncio
async def test_generate_image_auto_locks_face(ctx, provider):
    character_id = await _create_character(ctx)

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/generate-image"
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["generated_images"], data
    assert "/uploads/ai/images/" in data["generated_images"][0]
    # 首次出图即自动锁脸：基准图直接复用刚落盘的自有图片，种子/外观描述都落库
    assert "/uploads/ai/images/" in data["reference_image_url"]
    assert isinstance(data["image_seed"], int)
    assert "参考图" in data["visual_prompt"]

    # 走的是文生图（此时还没有基准图）
    kinds = [c[0] for c in provider.calls]
    assert kinds.count("generations") == 1
    assert "seed" not in provider.calls[0][1], "首次文生图不应带 seed"


@pytest.mark.asyncio
async def test_lock_face_stores_reference_without_calling_ai(ctx, provider):
    character_id = await _create_character(ctx, avatar_url=f"{provider.base}/files/face.png")

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/lock-face",
        json={"seed": 12345, "visual_prompt": "黑长直，红风衣"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["image_seed"] == 12345
    assert data["visual_prompt"] == "黑长直，红风衣"
    assert "/uploads/ai/characters/" in data["reference_image_url"]
    assert provider.calls == [], "锁脸不该调用任何 AI"

    stored = ctx.root / data["reference_image_url"].split("/uploads/", 1)[1].split("?")[0]
    assert stored.read_bytes() == PNG_BYTES, "基准图必须真的落盘"


# ==================== 已锁脸 → 图生图 ====================


@pytest.mark.asyncio
async def test_locked_character_uses_edits_with_seed(ctx, provider):
    character_id = await _create_character(ctx, avatar_url=f"{provider.base}/files/face.png")
    lock = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/lock-face",
        json={"seed": 777},
    )
    assert lock.status_code == 200, lock.text

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/generate-image"
    )

    assert resp.status_code == 200, resp.text
    edits = [c for c in provider.calls if c[0] == "edits"]
    assert len(edits) == 1, "锁脸后必须走图生图，不能再走文生图"
    _, body, content_type, auth = edits[0]
    assert "multipart/form-data" in content_type
    assert b'name="image"' in body and b'name="prompt"' in body
    assert b"777" in body, "seed 必须透传给 provider"
    assert auth == "Bearer k"
    # 文生图一次都不该被调用
    assert [c for c in provider.calls if c[0] == "generations"] == []


@pytest.mark.asyncio
async def test_provider_without_edits_returns_501_and_refunds_quota(ctx, provider):
    character_id = await _create_character(ctx, avatar_url=f"{provider.base}/files/face.png")
    await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/lock-face",
        json={"seed": 1},
    )
    FakeProvider.edits_status = 404

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/generate-image"
    )

    assert resp.status_code == 501, resp.text
    assert "参考图" in resp.json()["detail"]

    from sqlalchemy import select

    from app.models.ai_usage import AIUsage

    async with ctx.maker() as session:
        used = (
            await session.execute(select(AIUsage.count).where(AIUsage.user_id == "u1"))
        ).scalars().all()
    assert sum(used or [0]) == 0, "501 必须退回配额，不能让用户为能力不足买单"


# ==================== 三视图 ====================


@pytest.mark.asyncio
async def test_views_require_locked_face(ctx, provider):
    character_id = await _create_character(ctx)

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/views",
        json={"views": ["front", "side"]},
    )

    assert resp.status_code == 400
    assert "锁脸" in resp.json()["detail"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_views_reject_unknown_angle(ctx, provider):
    character_id = await _create_character(ctx, avatar_url=f"{provider.base}/files/face.png")
    await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/lock-face",
        json={"seed": 2},
    )

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/views",
        json={"views": ["front", "top-down; rm -rf /"]},
    )

    assert resp.status_code == 400
    assert provider.calls[1:] == [], "非法视角必须在调用 AI 之前被拒"


@pytest.mark.asyncio
async def test_views_generate_and_store_each_angle(ctx, provider):
    character_id = await _create_character(ctx, avatar_url=f"{provider.base}/files/face.png")
    await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/lock-face",
        json={"seed": 3},
    )

    resp = await ctx.client.post(
        f"/api/v1/projects/{ctx.project_id}/characters/{character_id}/views",
        json={"views": ["front", "side"]},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data["view_images"]) == {"front", "side"}
    for url in data["view_images"].values():
        assert "/uploads/ai/images/" in url
    assert len([c for c in provider.calls if c[0] == "edits"]) == 2
    assert len(data["generated_images"]) == 2, "三视图也要进形象库，便于复用"
