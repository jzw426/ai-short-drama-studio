"""排队竞态回归：worker 先于接口事务提交拿到消息时，不能把任务永久留在 queued。

现场（M3-1 容器全栈实测）：渲染接口历史上只 `db.flush()` 不 commit 就
`execute_render.delay()`，worker 偶发查不到任务行，日志只有一行
"[Render Task] Task ... not found"，任务状态永远 queued。
两处修复：
1. `backend/app/api/routes/render.py` 入队前先 commit；
2. worker 查不到行时退避重试，而不是直接 return。
"""
from __future__ import annotations

import asyncio

import pytest
from celery.exceptions import Retry

from app.tasks import render_task as rt


def test_missing_task_triggers_retry(monkeypatch):
    async def _missing(_task_id: str):
        return None

    monkeypatch.setattr(rt, "_load_task", _missing)

    with pytest.raises(Retry):
        rt.execute_render.apply(
            args=["11111111-1111-1111-1111-111111111111"], throw=True
        )


def test_missing_task_after_retries_logs_and_returns(monkeypatch, caplog):
    async def _missing(_task_id: str):
        return None

    monkeypatch.setattr(rt, "_load_task", _missing)

    async def _boom(*_a, **_kw):
        raise AssertionError("should not reach render_service")

    monkeypatch.setattr(rt.render_service, "execute_render", _boom)

    # 已经用尽重试次数：直接返回，不再抛 Retry（任务结束，日志留痕）
    with caplog.at_level("ERROR"):
        rt.execute_render.apply(
            args=["22222222-2222-2222-2222-222222222222"],
            throw=True,
            retries=rt.MAX_ATTEMPTS - 1,
        )
    assert any("not found" in rec.message for rec in caplog.records)
