"""路径解析回归：backend/data/ 不在版本库里，新环境必须先建父目录。

现场（推 CI 前静态审查 + 本机模拟）：`.gitignore` 忽略了 `backend/data/`，
GitHub Actions 全新 clone 后该目录不存在，`DATABASE_PATH` 指向
`backend/data/ci.db` 时 sqlite 直接报 "unable to open database file"，
pytest 与 alembic 两个 job 都会红。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_missing_data_dir_is_created(tmp_path: Path) -> None:
    db = tmp_path / "fresh" / "data" / "ci.db"
    assert not db.parent.exists()

    env = dict(os.environ)
    env.update(
        {
            "DATABASE_TYPE": "sqlite",
            "DATABASE_PATH": str(db),
            "SECRET_KEY": "a" * 64,
            "ENVIRONMENT": "test",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", "from app.core.config import settings; print(settings.DATABASE_PATH)"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert db.parent.is_dir(), "配置加载后数据库文件父目录仍不存在"


def test_relative_storage_path_still_under_backend() -> None:
    env = dict(os.environ)
    env.update(
        {
            "STORAGE_LOCAL_PATH": "uploads",
            "SECRET_KEY": "a" * 64,
            "ENVIRONMENT": "test",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", "from app.core.config import settings; print(settings.STORAGE_LOCAL_PATH)"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    resolved = Path(proc.stdout.strip().splitlines()[-1])
    assert resolved.is_absolute()
    assert resolved.parent == BACKEND_DIR
