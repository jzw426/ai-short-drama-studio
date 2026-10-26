"""Celery worker 连接池回归（M3-1 容器全栈实测出来的真故障）。

背景：Celery 每个任务在 `asyncio.run()` 里新建事件循环，而 async engine 的
连接池是进程级的。第一个任务用完的 asyncpg 连接留在池里，第二个任务在新循环
里复用它，asyncpg 直接抛：

    RuntimeError: Task ... got Future ... attached to a different loop

现场表现：worker 处理完第一个渲染任务后，后续任务永远停在 queued，接口侧
看不出错，只有 worker 日志里有异常。凡是 worker 里会用到的 async engine 都
必须是 NullPool：

- `app.tasks.render_task.celery_engine`：任务自己的查询引擎；
- `app.core.database.engine`：ai_service / render_service 里记账、取素材时用的
  全局 engine，worker 容器通过 `DATABASE_NULL_POOL=true` 切到 NullPool。

API 进程是单事件循环，继续用连接池，不能被 worker 的开关误伤。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

_PROBE = (
    "import json;"
    "from app.core.database import engine as app_engine;"
    "from app.tasks.render_task import celery_engine;"
    "print(json.dumps({"
    "'app': type(app_engine.pool).__name__,"
    "'celery': type(celery_engine.pool).__name__"
    "}))"
)


def _probe_pools(**overrides: str) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_TYPE": "postgres",
            "SECRET_KEY": "a" * 64,
            "ENVIRONMENT": "test",
        }
    )
    env.update(overrides)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_celery_task_engine_always_null_pool():
    # 这条与 env 无关：任务引擎只要不是 NullPool，第二个任务必挂
    assert _probe_pools()["celery"] == "NullPool"


def test_worker_global_engine_null_pool_enabled():
    assert _probe_pools(DATABASE_NULL_POOL="true")["app"] == "NullPool"


def test_api_engine_keeps_pool_by_default():
    # API 单事件循环进程继续走连接池，别被 worker 的开关误伤
    assert _probe_pools(DATABASE_NULL_POOL="false")["app"] != "NullPool"
