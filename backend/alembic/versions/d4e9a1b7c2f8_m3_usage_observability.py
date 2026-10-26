"""M3-4 AI 用量明细表 + 渲染失败分类

Revision ID: d4e9a1b7c2f8
Revises: c3d8f2a91b57
Create Date: 2026-10-26

新增：
- ai_usage_events：每次 AI 逻辑调用的明细账（成功/失败/超时），按 (user_id,
  created_at) 与 (operation, created_at) 聚合查询用。
- render_tasks.error_category：失败分类枚举，供 /ops/render-stats 聚合。

注意：estimated_cost_usd 是按 usage_pricing 的占位单价估算，非账单金额。
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e9a1b7c2f8"
down_revision = "c3d8f2a91b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "estimated_cost_usd", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("error_kind", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"]
    )
    op.create_index(
        "ix_ai_usage_events_user_created",
        "ai_usage_events",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_operation_created",
        "ai_usage_events",
        ["operation", "created_at"],
    )

    op.add_column(
        "render_tasks", sa.Column("error_category", sa.String(length=20), nullable=True)
    )
    op.create_index(
        "ix_render_tasks_error_category", "render_tasks", ["error_category"]
    )


def downgrade() -> None:
    op.drop_index("ix_render_tasks_error_category", table_name="render_tasks")
    op.drop_column("render_tasks", "error_category")

    op.drop_index(
        "ix_ai_usage_events_operation_created", table_name="ai_usage_events"
    )
    op.drop_index("ix_ai_usage_events_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_created_at", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
