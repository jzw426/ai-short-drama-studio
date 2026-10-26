"""m1b: 会话代际 + 渲染幂等/取消/断点

Revision ID: b7c1d2e3f401
Revises: cef2afd76e33
Create Date: 2026-10-26

M1 第二刀的三处结构变更：
1. users.token_version —— 登出/改密后旧 JWT 立即失效（替代黑名单表）。
2. render_tasks.idempotency_key —— 同一项目同 key 只排一次队，避免重复烧 AI 视频费。
3. render_tasks.cancel_requested / attempt / checkpoint —— 协作式取消、重试计数、
   已生成片段断点（重试不再重跑 AI）。
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c1d2e3f401"
down_revision = "cef2afd76e33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column("render_tasks", sa.Column("idempotency_key", sa.String(length=100), nullable=True))
    op.add_column(
        "render_tasks",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "render_tasks",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("render_tasks", sa.Column("checkpoint", sa.JSON(), nullable=True))

    op.create_index("ix_render_tasks_idempotency_key", "render_tasks", ["idempotency_key"])
    op.create_index("ix_render_tasks_cancel_requested", "render_tasks", ["cancel_requested"])
    # 同一项目内幂等键唯一；NULL 不参与唯一性（未传 key 的提交不受影响）
    op.create_index(
        "uq_render_tasks_project_idem",
        "render_tasks",
        ["project_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_render_tasks_project_idem", table_name="render_tasks")
    op.drop_index("ix_render_tasks_cancel_requested", table_name="render_tasks")
    op.drop_index("ix_render_tasks_idempotency_key", table_name="render_tasks")
    op.drop_column("render_tasks", "checkpoint")
    op.drop_column("render_tasks", "attempt")
    op.drop_column("render_tasks", "cancel_requested")
    op.drop_column("render_tasks", "idempotency_key")
    op.drop_column("users", "token_version")
