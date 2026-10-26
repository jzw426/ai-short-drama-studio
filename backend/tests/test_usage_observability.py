"""M3-4 可观测性：AI 用量记账 / 成本估算 / 渲染失败分类 / 运维统计接口。

覆盖范围：
- record_ai_usage_event：成功落库（含 token/成本/指标）、写库失败被吞掉不影响业务
- usage_pricing.estimate_cost：token 计价、按次计价、未知 provider 返回 0、环境变量覆盖
- render_task.classify_render_error：六类失败分类
- /api/v1/ops/usage 与 /api/v1/ops/render-stats：鉴权、聚合数值、operation 过滤
- /metrics 暴露 ai_calls_total / render_failures_total

全部用内存 sqlite + httpx.ASGITransport（同一事件循环内请求），
既避免"TestClient 跨 loop 复用连接"的坑，也不落盘（本机文件 SQLite DDL 很慢）。
"""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - 注册全部模型，create_all 才能建出外键依赖的表
from app.api.routes import ops
from app.core import usage_pricing
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.core.metrics import metrics
from app.core.time_utils import utc_now
from app.models.ai_usage import AIUsageEvent
from app.models.asset import RenderTask
from app.services.ai_service import AIUnavailableError, record_ai_usage_event
from app.services.render_service import RenderCancelled
from app.tasks.render_task import classify_render_error


def _make_app(engine, *, authenticated: bool = True) -> FastAPI:
    """只挂 ops 路由的最小应用；鉴权与数据库都用 dependency_overrides 替换。"""
    app = FastAPI()
    app.include_router(ops.router, prefix="/api/v1")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    if authenticated:
        async def _override_user():
            return object()

        app.dependency_overrides[get_current_user] = _override_user
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ==================== 记账 ====================


@pytest.mark.asyncio
async def test_record_ai_usage_event_success():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_schema(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async with maker() as session:
            event = await record_ai_usage_event(
                operation="script",
                status="success",
                provider="agnes",
                model="agnes-2.0-flash",
                prompt_tokens=1000,
                completion_tokens=2000,
                duration_ms=1234,
                user_id="u1",
                project_id="p1",
                session=session,
            )

        assert event is not None
        # agnes-2.0-flash: 0.0002/1K 输入 + 0.0006/1K 输出
        assert event.estimated_cost_usd == pytest.approx(0.0014)
        assert event.duration_ms == 1234

        async with maker() as session:
            row = (await session.execute(select(AIUsageEvent))).scalar_one()
        assert row.operation == "script"
        assert row.status == "success"
        assert row.error_kind == ""
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 2000
        assert row.user_id == "u1"
        assert row.project_id == "p1"

        snapshot = metrics.snapshot()
        assert any(
            item["operation"] == "script" and item["status"] == "success"
            for item in snapshot["ai_calls_total"]
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_ai_usage_event_does_not_raise_on_db_error():
    """记账失败只 warning：不能让一次已经付费的 AI 调用失败。"""

    class _BrokenFactory:
        def __call__(self):
            raise RuntimeError("database is down")

    event = await record_ai_usage_event(
        operation="video",
        status="failure",
        provider="agnes",
        model="agnes-video-v2.0",
        error_kind="ai_unavailable",
        session_factory=_BrokenFactory(),
    )

    assert event is None
    # 落库失败也要计入进程内指标
    snapshot = metrics.snapshot()
    assert any(
        item["operation"] == "video" and item["status"] == "failure"
        for item in snapshot["ai_calls_total"]
    )


# ==================== 价格估算 ====================


def test_estimate_cost_token_based():
    cost = usage_pricing.estimate_cost(
        "agnes", "agnes-2.0-flash", prompt_tokens=1000, completion_tokens=2000
    )
    assert cost == pytest.approx(0.0014)


def test_estimate_cost_unknown_provider_is_zero():
    assert usage_pricing.estimate_cost(
        "nobody", "no-such-model", prompt_tokens=5000, completion_tokens=5000
    ) == 0.0
    assert usage_pricing.get_price("nobody", "no-such-model")["per_call_usd"] == 0.0


def test_estimate_cost_per_call_without_tokens():
    # 视频类响应没有 usage，按次计价
    assert usage_pricing.estimate_cost("agnes", "agnes-video-v2.0") == pytest.approx(0.05)
    assert usage_pricing.estimate_cost("kling", "kling-v1.6") == pytest.approx(0.10)


def test_estimate_cost_env_override(monkeypatch):
    monkeypatch.setenv(
        usage_pricing.PRICING_ENV_VAR,
        '{"agnes/agnes-2.0-flash": {"input_per_1k_usd": 1.0, "output_per_1k_usd": 2.0}}',
    )
    # 清空解析缓存，避免读到别的测试留下的环境变量快照
    monkeypatch.setattr(usage_pricing, "_env_cache", {"raw": None, "parsed": {}})

    cost = usage_pricing.estimate_cost(
        "agnes", "agnes-2.0-flash", prompt_tokens=1000, completion_tokens=1000
    )
    assert cost == pytest.approx(3.0)


# ==================== 渲染失败分类 ====================


def test_classify_ai_unavailable():
    assert classify_render_error(AIUnavailableError("所有 provider 均不可用")) == "ai_unavailable"


def test_classify_timeout():
    assert classify_render_error(TimeoutError("poll timeout")) == "timeout"


def test_classify_ffmpeg():
    assert classify_render_error(None, message="ffmpeg exited with code 1") == "ffmpeg"


def test_classify_storage():
    assert classify_render_error(None, message="MinIO 上传失败: connection refused") == "storage"


def test_classify_cancelled():
    assert classify_render_error(cancelled=True) == "cancelled"
    assert classify_render_error(RenderCancelled()) == "cancelled"


def test_classify_other():
    assert classify_render_error(None, message="未知错误") == "other"
    assert classify_render_error() == "other"


# ==================== 接口：/ops/usage ====================


def _seed_usage_events(now):
    return [
        AIUsageEvent(
            operation="script",
            provider="agnes",
            model="agnes-2.0-flash",
            status="success",
            prompt_tokens=1000,
            completion_tokens=2000,
            duration_ms=1200,
            estimated_cost_usd=0.0014,
            user_id="u1",
            project_id="p1",
            created_at=now,
        ),
        AIUsageEvent(
            operation="script",
            provider="agnes",
            model="agnes-2.0-flash",
            status="failure",
            error_kind="ai_unavailable",
            duration_ms=300,
            user_id="u1",
            created_at=now,
        ),
        AIUsageEvent(
            operation="video",
            provider="agnes",
            model="agnes-video-v2.0",
            status="timeout",
            error_kind="timeout",
            duration_ms=5000,
            estimated_cost_usd=0.05,
            created_at=now - timedelta(days=2),
        ),
        # 窗口外（30 天前）不应计入
        AIUsageEvent(
            operation="script",
            status="success",
            prompt_tokens=10,
            completion_tokens=10,
            created_at=now - timedelta(days=30),
        ),
    ]


@pytest.mark.asyncio
async def test_ops_usage_aggregates_and_filters():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = utc_now()
    try:
        await _create_schema(engine)
        async with maker() as session:
            session.add_all(_seed_usage_events(now))
            await session.commit()

        async with _client(_make_app(engine)) as client:
            resp = await client.get("/api/v1/ops/usage?days=7")
            assert resp.status_code == 200
            data = resp.json()

            assert data["days"] == 7
            assert len(data["daily"]) == 7
            assert data["daily"][-1]["date"] == now.date().isoformat()

            total = data["total"]
            assert total["calls"] == 3
            assert total["success"] == 1
            assert total["failure"] == 1
            assert total["timeout"] == 1
            assert total["prompt_tokens"] == 1000
            assert total["completion_tokens"] == 2000
            assert total["tokens"] == 3000
            assert total["estimated_cost_usd"] == pytest.approx(0.0514)
            assert total["success_rate"] == pytest.approx(1 / 3, abs=1e-4)

            filtered = await client.get("/api/v1/ops/usage?days=7&operation=video")
            assert filtered.status_code == 200
            assert filtered.json()["total"]["calls"] == 1
            assert filtered.json()["total"]["timeout"] == 1
            assert filtered.json()["total"]["estimated_cost_usd"] == pytest.approx(0.05)
            assert filtered.json()["daily"][-3]["calls"] == 1

            bad = await client.get("/api/v1/ops/usage?days=7&operation=image")
            assert bad.status_code == 400
            assert "operation" in bad.json()["detail"]
    finally:
        await engine.dispose()


# ==================== 接口：/ops/render-stats ====================


@pytest.mark.asyncio
async def test_ops_render_stats_aggregation():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = utc_now()
    try:
        await _create_schema(engine)
        async with maker() as session:
            session.add_all(
                [
                    RenderTask(project_id="p1", name="r1", status="completed", duration=10.0, created_at=now),
                    RenderTask(project_id="p1", name="r2", status="completed", duration=20.0, created_at=now),
                    RenderTask(
                        project_id="p1", name="r3", status="failed",
                        error_category="ffmpeg", error_message="ffmpeg exited 1", created_at=now,
                    ),
                    RenderTask(
                        project_id="p1", name="r4", status="failed",
                        error_category="ai_unavailable", error_message="所有 provider 均不可用", created_at=now,
                    ),
                    # 历史数据没有分类 -> 归入 other
                    RenderTask(project_id="p1", name="r5", status="failed", created_at=now),
                    RenderTask(project_id="p1", name="r6", status="queued", created_at=now),
                ]
            )
            await session.commit()

        async with _client(_make_app(engine)) as client:
            resp = await client.get("/api/v1/ops/render-stats?days=7")
            assert resp.status_code == 200
            payload = resp.json()

            assert payload["total"] == 6
            assert payload["completed"] == 2
            assert payload["failed"] == 3
            assert payload["running"] == 1
            assert payload["success_rate"] == pytest.approx(0.4)
            assert payload["avg_duration_seconds"] == pytest.approx(15.0)
            assert payload["by_status"]["failed"] == 3
            # 按 (count 降序, category 升序) 排序
            assert payload["failure_categories"] == [
                {"category": "ai_unavailable", "count": 1},
                {"category": "ffmpeg", "count": 1},
                {"category": "other", "count": 1},
            ]
    finally:
        await engine.dispose()


# ==================== 鉴权 / 指标 ====================


@pytest.mark.asyncio
async def test_ops_usage_and_render_stats_require_auth():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_schema(engine)
        async with _client(_make_app(engine, authenticated=False)) as client:
            assert (await client.get("/api/v1/ops/usage")).status_code == 401
            assert (await client.get("/api/v1/ops/render-stats")).status_code == 401
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_metrics_snapshot_exposes_ai_and_render_counters():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metrics.record_ai_call("storyboard", "failure")
    metrics.record_render_failure("storage")
    try:
        await _create_schema(engine)
        async with _client(_make_app(engine)) as client:
            resp = await client.get("/api/v1/metrics")
            assert resp.status_code == 200
            payload = resp.json()

        assert any(
            item["operation"] == "storyboard" and item["status"] == "failure"
            for item in payload["ai_calls_total"]
        )
        assert any(
            item["category"] == "storage" and item["count"] >= 1
            for item in payload["render_failures_total"]
        )
    finally:
        await engine.dispose()
