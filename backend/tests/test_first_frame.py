"""M4-3 首帧图 / 场景资产 / 异步视频作业消费 测试。

覆盖的三条链路：
1. 首帧：分镜镜头 + 角色锁脸资产 + 场景定场资产 → 一张首帧图（默认复用，
   regenerate 才重新出图且扣配额，失败一律退款）；
2. 场景资产：同一 (project, scene_ref, view) 是 upsert（不撞唯一索引 500），
   source=ai 按次计费并转存到自有存储；
3. 渲染：只消费 ai_video_jobs 里已完成的产物，默认不再同步调用付费视频生成
   （RENDER_ALLOW_INLINE_VIDEO=False），没绑定时报错要能直接指导用户操作。
"""
import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - 注册全部模型（含 scene_asset / video_job）
import app.core.database as database_module
from app.api.routes import scene_assets as scene_assets_route
from app.api.routes import storyboards as storyboards_route
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.core.time_utils import utc_now
from app.models.ai_usage import AIUsage
from app.models.character import Character
from app.models.project import Project
from app.models.scene_asset import SceneAsset
from app.models.storyboard import Shot, Storyboard
from app.models.video_job import AIVideoJob
from app.services.ai_service import (
    AIUnavailableError,
    ImageCapabilityError,
    ai_service,
)
from app.services.first_frame import load_shot_characters
from app.services.render_service import RenderService, RenderStepError, build_spec

# 模块级单例把包属性 app.services.render_service 覆盖成了实例，拿模块必须走 sys.modules
RENDER_MODULE = sys.modules["app.services.render_service"]

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\x0d\x0a-\xb4\x00\x00\x00\x00IEND\xaeB\x60\x82"
)

CALLS: list = []


class FakeProvider(BaseHTTPRequestHandler):
    """冒充 OpenAI 兼容图片服务：generations / edits / 文件下载。"""

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
    # 熔断状态挂在全局单例上，跨用例会残留：每个用例从没有冷却开始
    ai_service._provider_states.clear()
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
    """真实文件库 + 真实存储目录。

    这里刻意不用内存库：render_service._load_shots / _completed_video_map 在函数内部
    import async_session 自己开会话，必须和请求共用同一个文件库才能看到同一批数据。
    """
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(upload_root))
    monkeypatch.setattr(settings, "AI_DAILY_QUOTA", 100)

    db_path = tmp_path / "m4.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    project_id = str(uuid.uuid4())
    character_id = str(uuid.uuid4())
    shot1_id = str(uuid.uuid4())
    shot2_id = str(uuid.uuid4())
    async with maker() as session:
        session.add(Project(id=project_id, title="首帧项目", owner_id="u1"))
        await session.flush()
        session.add(
            Character(
                id=character_id,
                project_id=project_id,
                name="林夜",
                gender="female",
                age=24,
                traits=["冷静", "毒舌"],
                description="黑长直，红风衣，左眼下有泪痣",
            )
        )
        storyboard = Storyboard(project_id=project_id)
        session.add(storyboard)
        await session.flush()
        session.add_all(
            [
                Shot(
                    id=shot1_id,
                    storyboard_id=storyboard.id,
                    shot_number=1,
                    label="开场",
                    description="林夜站在霓虹灯下",
                    camera_angle="缓慢推镜",
                    scene_ref="雨夜街角",
                    character_refs=[character_id],
                    sort_order=0,
                ),
                Shot(
                    id=shot2_id,
                    storyboard_id=storyboard.id,
                    shot_number=2,
                    label="空镜",
                    description="雨滴打在积水路面",
                    camera_angle="俯拍",
                    sort_order=1,
                ),
            ]
        )
        await session.commit()

    # render_service 里 from app.core.database import async_session 是函数内导入，
    # 打补丁到模块属性即可让渲染侧读到同一个测试库
    monkeypatch.setattr(database_module, "async_session", maker)

    app = FastAPI()
    app.include_router(storyboards_route.router, prefix="/api/v1")
    app.include_router(scene_assets_route.router, prefix="/api/v1")

    async def _override_db():
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
    monkeypatch.setattr(ai_service, "usage_session_factory", maker)

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        yield SimpleNamespace(
            client=client,
            maker=maker,
            project_id=project_id,
            character_id=character_id,
            shot1_id=shot1_id,
            shot2_id=shot2_id,
            root=upload_root,
        )
    finally:
        await client.aclose()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def first_frame_url(ctx, shot_id: str) -> str:
    return f"/api/v1/projects/{ctx.project_id}/storyboard/shots/{shot_id}/first-frame"


def video_prompt_url(ctx, shot_id: str) -> str:
    return f"/api/v1/projects/{ctx.project_id}/storyboard/shots/{shot_id}/video-prompt"


def scenes_url(ctx) -> str:
    return f"/api/v1/projects/{ctx.project_id}/scene-assets"


async def _quota_used(ctx) -> int:
    async with ctx.maker() as session:
        rows = (
            await session.execute(select(AIUsage.count).where(AIUsage.user_id == "u1"))
        ).scalars().all()
    return sum(rows or [0])


async def _get_shot(ctx, shot_id: str) -> Shot:
    async with ctx.maker() as session:
        return await session.get(Shot, shot_id)


async def _update_shot(ctx, shot_id: str, **fields) -> None:
    async with ctx.maker() as session:
        shot = await session.get(Shot, shot_id)
        for key, value in fields.items():
            setattr(shot, key, value)
        await session.commit()


async def _update_character(ctx, **fields) -> None:
    async with ctx.maker() as session:
        character = await session.get(Character, ctx.character_id)
        for key, value in fields.items():
            setattr(character, key, value)
        await session.commit()


async def _lock_character(ctx, seed: int = 4242) -> None:
    """把基准图写进自有存储并锁脸（不走接口，聚焦首帧链路本身）。"""
    ref_dir = ctx.root / "ai" / "characters"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "ref.png").write_bytes(PNG_BYTES)
    await _update_character(
        ctx,
        reference_image_url="/uploads/ai/characters/ref.png",
        image_seed=seed,
        visual_prompt="黑长直，红风衣，左眼下有泪痣",
    )


async def _seed_job(ctx, shot_id, status: str, video_url, minutes_ago: int = 0) -> None:
    from datetime import timedelta

    async with ctx.maker() as session:
        session.add(
            AIVideoJob(
                project_id=ctx.project_id,
                shot_id=shot_id,
                prompt="",
                status=status,
                video_url=video_url,
                created_at=utc_now() - timedelta(minutes=minutes_ago),
            )
        )
        await session.commit()


def generations_payloads(provider) -> list:
    return [c[1] for c in provider.calls if c[0] == "generations"]


def edits_calls(provider) -> list:
    return [c for c in provider.calls if c[0] == "edits"]


# ==================== 首帧：生成 / 复用 / 重出 ====================


@pytest.mark.asyncio
async def test_first_frame_generates_signed_image_and_persists(ctx, provider):
    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "/uploads/ai/frames/" in data["image_url"], data
    assert "sig=" in data["image_url"], "首帧图必须签名后返回，不能裸给 /uploads 路径"
    assert data["reused"] is False
    assert data["characters_used"] == ["林夜"]
    # prompt 三类上下文都要在：镜头本身、场景、角色外观
    assert "镜头 1" in data["prompt"]
    assert "雨夜街角" in data["prompt"]
    assert "林夜" in data["prompt"]
    assert "电影分镜首帧" in data["prompt"]

    payloads = generations_payloads(provider)
    assert len(payloads) == 1, "一次首帧 = 一次出图"
    assert payloads[0]["prompt"] == data["prompt"]
    assert await _quota_used(ctx) == 1

    stored = await _get_shot(ctx, ctx.shot1_id)
    assert stored.image_url.startswith(f"/uploads/ai/frames/{ctx.project_id}/")
    assert "sig=" not in stored.image_url, "库里存规范 URL，签名只在响应阶段生成"
    assert (ctx.root / stored.image_url.split("/uploads/", 1)[1]).read_bytes() == PNG_BYTES


@pytest.mark.asyncio
async def test_first_frame_reuses_existing_without_ai_or_quota(ctx, provider):
    await _update_shot(ctx, ctx.shot1_id, image_url="/uploads/ai/frames/existing.png")

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={"regenerate": False})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reused"] is True
    assert data["image_url"].startswith("/uploads/ai/frames/existing.png")
    assert "sig=" in data["image_url"]
    assert provider.calls == [], "有首帧时不能打 provider"
    assert await _quota_used(ctx) == 0, "复用首帧不扣配额"


@pytest.mark.asyncio
async def test_first_frame_regenerate_calls_ai_again(ctx, provider):
    await _update_shot(ctx, ctx.shot1_id, image_url="/uploads/ai/frames/old.png")

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={"regenerate": True})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reused"] is False
    assert "/uploads/ai/frames/existing" not in data["image_url"]
    assert "/uploads/ai/frames/old.png" not in data["image_url"]
    assert len(generations_payloads(provider)) == 1
    assert await _quota_used(ctx) == 1

    stored = await _get_shot(ctx, ctx.shot1_id)
    assert stored.image_url != "/uploads/ai/frames/old.png"


@pytest.mark.asyncio
async def test_first_frame_unknown_shot_returns_404(ctx, provider):
    resp = await ctx.client.post(
        first_frame_url(ctx, "no-such-shot"), json={"regenerate": True}
    )

    assert resp.status_code == 404, resp.text
    assert "镜头不存在" in resp.json()["detail"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_first_frame_ai_failure_returns_503_and_refunds(ctx, provider, monkeypatch):
    async def boom(*args, **kwargs):
        raise AIUnavailableError("provider down")

    monkeypatch.setattr(ai_service, "generate_image", boom)

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 503, resp.text
    assert "首帧" in resp.json()["detail"]
    assert await _quota_used(ctx) == 0, "失败必须退款"
    assert (await _get_shot(ctx, ctx.shot1_id)).image_url is None


@pytest.mark.asyncio
async def test_first_frame_capability_error_returns_502_and_refunds(ctx, provider, monkeypatch):
    async def boom(*args, **kwargs):
        raise ImageCapabilityError("no edits support")

    monkeypatch.setattr(ai_service, "generate_image", boom)

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 502, resp.text
    assert "图生图" in resp.json()["detail"]
    assert await _quota_used(ctx) == 0


# ==================== 首帧：锁脸参考图 + 场景参考文本 ====================


@pytest.mark.asyncio
async def test_first_frame_locked_character_carries_reference_and_seed(ctx, provider):
    await _lock_character(ctx, seed=4242)

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "与参考图同一角色" in data["prompt"]
    assert "黑长直，红风衣，左眼下有泪痣" in data["prompt"]

    edits = edits_calls(provider)
    assert len(edits) == 1, "已锁脸必须走图生图"
    assert generations_payloads(provider) == []
    _, body, content_type, auth = edits[0]
    assert "multipart/form-data" in content_type
    assert b"4242" in body, "角色种子必须透传给 provider"
    assert body.count(b'name="image"') == 1, "一张参考图只能喂一个角色"
    assert "与参考图同一角色".encode() in body
    assert auth == "Bearer k"
    assert "/uploads/ai/frames/" in data["image_url"]


@pytest.mark.asyncio
async def test_scene_wide_asset_enters_prompt_as_text_reference(ctx, provider):
    """场景定场图只以文本进入 prompt（不占参考图位），但必须真的被读到。"""
    upload = await ctx.client.post(
        scenes_url(ctx),
        json={
            "scene_ref": "雨夜街角",
            "view": "wide",
            "source": "upload",
            "url": "/uploads/ai/scenes/self/wide.png",
        },
    )
    assert upload.status_code == 201, upload.text
    scene_prompt = "雨夜街角，霓虹灯与湿滑路面，暖橙招牌灯"
    # 直接给资产写上已知 prompt（upload 分支不会自动造 prompt）
    async with ctx.maker() as session:
        asset = (await session.execute(select(SceneAsset))).scalar_one()
        asset.prompt = scene_prompt
        await session.commit()

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert f"场景参考：{scene_prompt}" in data["prompt"]
    payloads = generations_payloads(provider)
    assert len(payloads) == 1
    assert scene_prompt in payloads[0]["prompt"]
    assert "image" not in payloads[0], "文生图请求里不应出现参考图字段（参考图走 edits 多部件）"


@pytest.mark.asyncio
async def test_medium_scene_view_is_not_used_as_reference(ctx, provider):
    """特写/中景不当作场景参考：会把构图锁死在人物身上。"""
    async with ctx.maker() as session:
        session.add(
            SceneAsset(
                project_id=ctx.project_id,
                scene_ref="雨夜街角",
                view="medium",
                url="/uploads/ai/scenes/self/medium.png",
                source="upload",
                prompt="中景构图，林夜半身",
            )
        )
        await session.commit()

    resp = await ctx.client.post(first_frame_url(ctx, ctx.shot1_id), json={})

    assert resp.status_code == 200, resp.text
    assert "场景参考" not in resp.json()["prompt"]


# ==================== 场景资产：upsert / 出图 / 删除 ====================


@pytest.mark.asyncio
async def test_scene_asset_upload_upserts_without_500(ctx, provider):
    url = scenes_url(ctx)
    payload = {
        "scene_ref": "雨夜街角",
        "view": "wide",
        "source": "upload",
        "url": f"{provider.base}/files/scene1.png",
    }
    first = await ctx.client.post(url, json=payload)
    assert first.status_code == 201, first.text
    body = first.json()
    assert "/uploads/ai/scenes/" in body["url"]
    assert "sig=" in body["url"]
    assert body["source"] == "upload"

    payload["url"] = f"{provider.base}/files/scene2.png"
    second = await ctx.client.post(url, json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == body["id"], "同场景同视角必须覆盖同一行，而不是新增"

    async with ctx.maker() as session:
        rows = (await session.execute(select(SceneAsset))).scalars().all()
    assert len(rows) == 1, "唯一索引保证只有一行"

    listed = await ctx.client.get(url, params={"scene_ref": "雨夜街角"})
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
    assert "sig=" in items[0]["url"]

    other = await ctx.client.get(url, params={"scene_ref": "不存在的场景"})
    assert other.json() == []


@pytest.mark.asyncio
async def test_scene_asset_ai_source_generates_and_charges(ctx, provider):
    resp = await ctx.client.post(
        scenes_url(ctx),
        json={
            "scene_ref": "雨夜街角",
            "view": "establishing",
            "source": "ai",
            "prompt": "霓虹雨夜",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "/uploads/ai/scenes/" in body["url"]
    assert body["source"] == "ai"
    payloads = generations_payloads(provider)
    assert len(payloads) == 1
    assert "霓虹雨夜" in payloads[0]["prompt"]
    assert "establishing 视角" in payloads[0]["prompt"]
    assert await _quota_used(ctx) == 1

    async with ctx.maker() as session:
        row = (await session.execute(select(SceneAsset))).scalar_one()
    assert row.source == "ai"
    assert "establishing 视角" in row.prompt


@pytest.mark.asyncio
async def test_scene_asset_ai_failure_refunds_quota(ctx, provider, monkeypatch):
    async def boom(*args, **kwargs):
        raise AIUnavailableError("provider down")

    monkeypatch.setattr(ai_service, "generate_image", boom)

    resp = await ctx.client.post(
        scenes_url(ctx),
        json={"scene_ref": "雨夜街角", "view": "wide", "source": "ai"},
    )

    assert resp.status_code == 503, resp.text
    assert await _quota_used(ctx) == 0
    async with ctx.maker() as session:
        assert (await session.execute(select(SceneAsset))).scalars().all() == []


@pytest.mark.asyncio
async def test_scene_asset_upload_requires_url(ctx, provider):
    resp = await ctx.client.post(
        scenes_url(ctx), json={"scene_ref": "雨夜街角", "view": "close", "source": "upload"}
    )

    assert resp.status_code == 400, resp.text
    assert "url" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scene_asset_rejects_unknown_view(ctx, provider):
    resp = await ctx.client.post(
        scenes_url(ctx),
        json={"scene_ref": "雨夜街角", "view": "top-down", "source": "upload", "url": "/x.png"},
    )

    assert resp.status_code == 400, resp.text
    assert "视角" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scene_asset_delete_is_idempotent_404_afterwards(ctx, provider):
    created = await ctx.client.post(
        scenes_url(ctx),
        json={
            "scene_ref": "雨夜街角",
            "view": "wide",
            "source": "upload",
            "url": "/uploads/ai/scenes/self/wide.png",
        },
    )
    asset_id = created.json()["id"]

    deleted = await ctx.client.delete(f"{scenes_url(ctx)}/{asset_id}")
    assert deleted.status_code == 204, deleted.text

    again = await ctx.client.delete(f"{scenes_url(ctx)}/{asset_id}")
    assert again.status_code == 404
    assert "场景资产不存在" in again.json()["detail"]


# ==================== 镜头视频提示词端点 ====================


@pytest.mark.asyncio
async def test_video_prompt_endpoint_persists_and_signs(ctx, provider):
    await _update_shot(ctx, ctx.shot1_id, video_url="/uploads/ai/videos/p1/clip.mp4")

    resp = await ctx.client.post(
        video_prompt_url(ctx, ctx.shot1_id), json={"video_prompt": "  推镜 3 秒，雨丝斜落  "}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["video_prompt"] == "推镜 3 秒，雨丝斜落", "提示词要 strip 后落库"
    assert "sig=" in body["video_url"], "镜头响应里的 video_url 必须签名"
    stored = await _get_shot(ctx, ctx.shot1_id)
    assert stored.video_prompt == "推镜 3 秒，雨丝斜落"


# ==================== 角色引用解析（id / 名字两种历史数据） ====================


@pytest.mark.asyncio
async def test_load_shot_characters_accepts_id_and_name(ctx, provider):
    async with ctx.maker() as session:
        shot = await session.get(Shot, ctx.shot1_id)
        by_id = await load_shot_characters(session, ctx.project_id, shot)
        assert [c.id for c in by_id] == [ctx.character_id]

        shot.character_refs = ["林夜"]
        by_label = await load_shot_characters(session, ctx.project_id, shot)
        assert [c.id for c in by_label] == [ctx.character_id]

        shot.character_refs = ["查无此人"]
        assert await load_shot_characters(session, ctx.project_id, shot) == []


# ==================== 渲染：一次性查已完成作业，不在 _pick_source 里开连接 ====================


@pytest.mark.asyncio
async def test_load_shots_exposes_shot_id(ctx, provider):
    service = RenderService()
    shots = await service._load_shots(ctx.project_id)

    assert [s["id"] for s in shots] == [ctx.shot1_id, ctx.shot2_id]
    assert [s["shot_number"] for s in shots] == [1, 2]


@pytest.mark.asyncio
async def test_completed_video_map_only_completed_and_keeps_latest(ctx, provider):
    service = RenderService()
    await _seed_job(ctx, ctx.shot1_id, "completed", "/uploads/ai/videos/p1/old.mp4", minutes_ago=5)
    await _seed_job(ctx, ctx.shot1_id, "completed", "/uploads/ai/videos/p1/new.mp4", minutes_ago=1)
    await _seed_job(ctx, ctx.shot1_id, "polling", "/uploads/ai/videos/p1/polling.mp4", minutes_ago=0)
    await _seed_job(ctx, ctx.shot2_id, "failed", "/uploads/ai/videos/p1/failed.mp4", minutes_ago=0)
    # 没有关联镜头的作业不能进映射（历史上允许先批量生成后绑定）
    async with ctx.maker() as session:
        session.add(
            AIVideoJob(
                project_id=ctx.project_id,
                shot_id=None,
                prompt="",
                status="completed",
                video_url="/uploads/ai/videos/p1/unbound.mp4",
                created_at=utc_now(),
            )
        )
        await session.commit()

    mapping = await service._completed_video_map(ctx.project_id)

    assert mapping == {ctx.shot1_id: "/uploads/ai/videos/p1/new.mp4"}


@pytest.mark.asyncio
async def test_pick_source_consumes_completed_job_without_ai(ctx, provider, monkeypatch):
    (ctx.root / "ai" / "videos" / "p1").mkdir(parents=True, exist_ok=True)
    (ctx.root / "ai" / "videos" / "p1" / "done.mp4").write_bytes(b"fake-mp4")
    await _seed_job(ctx, ctx.shot1_id, "completed", "/uploads/ai/videos/p1/done.mp4")

    async def boom(**kwargs):
        raise AssertionError("已有完成作业时不应调用付费视频生成")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", boom)
    monkeypatch.setattr(settings, "RENDER_ALLOW_INLINE_VIDEO", False)

    service = RenderService()
    shots = await service._load_shots(ctx.project_id)
    mapping = await service._completed_video_map(ctx.project_id)
    spec, _ = build_spec({})

    segments = await service._render_segments(
        shots[:1], str(ctx.root), spec, None, None, {}, ctx.project_id, mapping
    )

    assert segments[0]["status"] == "success", segments
    assert segments[0]["video_url"] == "/uploads/ai/videos/p1/done.mp4"
    assert segments[0]["source"] == "local"


@pytest.mark.asyncio
async def test_pick_source_unbound_shot_explains_next_step(ctx, provider, monkeypatch):
    async def boom(**kwargs):
        raise AssertionError("默认配置下渲染链路不应同步调用 AI 视频生成")

    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", boom)
    monkeypatch.setattr(settings, "RENDER_ALLOW_INLINE_VIDEO", False)

    service = RenderService()
    spec, _ = build_spec({})
    shot = {"id": ctx.shot2_id, "shot_number": 2, "duration": 3.0, "description": "空镜", "label": "空镜"}

    with pytest.raises(RenderStepError) as excinfo:
        await service._pick_source(shot, {}, spec, ctx.project_id, {})

    message = str(excinfo.value)
    assert "镜头 2 未绑定素材" in message
    assert "请先在分镜页生成视频" in message


@pytest.mark.asyncio
async def test_pick_source_uses_inline_only_when_explicitly_enabled(ctx, provider, monkeypatch):
    seen = {}

    async def fake_generate(**kwargs):
        seen["prompt"] = kwargs.get("prompt")
        return "https://provider-cdn.example/tmp/clip.mp4"

    async def fake_persist(url, prefix, **kwargs):
        seen["url"] = url
        seen["prefix"] = prefix
        return "/uploads/ai/videos/p1/inline.mp4"

    monkeypatch.setattr(settings, "RENDER_ALLOW_INLINE_VIDEO", True)
    monkeypatch.setattr(RENDER_MODULE.ai_service, "generate_video", fake_generate)
    monkeypatch.setattr(RENDER_MODULE, "persist_remote_media", fake_persist)

    service = RenderService()
    spec, _ = build_spec({})
    shot = {"id": ctx.shot2_id, "shot_number": 2, "duration": 3.0, "description": "雨滴打在积水路面", "label": "空镜"}

    url, kind = await service._pick_source(shot, {}, spec, ctx.project_id, {})

    assert url == "/uploads/ai/videos/p1/inline.mp4"
    assert kind == "local"
    assert seen["url"] == "https://provider-cdn.example/tmp/clip.mp4"
    assert seen["prefix"].startswith("ai/videos/")
    assert seen["prompt"] == "雨滴打在积水路面"
