#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合幂等迁移脚本（SQLite 场景）

覆盖 P0/P1 需要的 schema 变更，可重复执行，不破坏已有数据：
1. render_tasks.celery_task_id 列（P0 渲染取消）
2. users 表（P0 认证体系）
3. projects.owner_id 列（P1 用户归属预留，默认空）

用法：
    python scripts/migrate_schema.py
"""

import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "backend", "data", "app.db"))

USERS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(512) NOT NULL,
    display_name VARCHAR(64) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME
)
"""


def add_column_if_missing(conn, table: str, column: str, ddl: str) -> bool:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in cols:
        return False
    conn.execute(ddl)
    return True


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"[MIGRATE] 数据库不存在，跳过: {DB_PATH}")
        return 0

    conn = sqlite3.connect(DB_PATH)
    try:
        changes = []

        # 1. render_tasks.celery_task_id
        if add_column_if_missing(
            conn,
            "render_tasks",
            "celery_task_id",
            "ALTER TABLE render_tasks ADD COLUMN celery_task_id VARCHAR(64)",
        ):
            changes.append("render_tasks.celery_task_id")
            # 为列建立索引（幂等）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_render_tasks_celery_task_id ON render_tasks (celery_task_id)"
            )

        # 2. users 表
        conn.execute(USERS_TABLE_DDL)
        user_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchall()
        if user_tables:
            changes.append("users 表")

        # 3. projects.owner_id（用户归属预留）
        if add_column_if_missing(
            conn,
            "projects",
            "owner_id",
            "ALTER TABLE projects ADD COLUMN owner_id VARCHAR(36)",
        ):
            changes.append("projects.owner_id")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"
            )

        conn.commit()

        if changes:
            print(f"[MIGRATE] 已应用变更: {', '.join(changes)}")
        else:
            print("[MIGRATE] 无需变更，schema 已是最新")

        # 校验
        cols = {row[1] for row in conn.execute("PRAGMA table_info(render_tasks)").fetchall()}
        assert "celery_task_id" in cols, "render_tasks.celery_task_id 缺失！"
        users = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchall()
        assert users, "users 表不存在！"
        print("[MIGRATE] 校验通过")
        return 0
    except sqlite3.Error as e:
        print(f"[MIGRATE] 失败: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
