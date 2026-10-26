"""M3-3 渲染任务字幕文件地址

Revision ID: e5a7c1d9f206
Revises: d4e9a1b7c2f8
Create Date: 2026-10-26

新增 render_tasks.subtitle_url：字幕文件（srt）单独落一份存储，
成片 URL 之外再给用户一个可下载/可复用的字幕地址。
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a7c1d9f206"
down_revision = "d4e9a1b7c2f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("render_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("subtitle_url", sa.String(length=2048), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("render_tasks") as batch_op:
        batch_op.drop_column("subtitle_url")
