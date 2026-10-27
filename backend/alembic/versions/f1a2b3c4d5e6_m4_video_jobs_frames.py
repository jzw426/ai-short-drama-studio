"""M4-3 图生视频：首帧图字段 + 视频作业表 + 场景资产表

三处改动：
1. `shots` 加 `image_url`（首帧图）与 `video_prompt`（喂给视频模型的提示词）；
2. 新表 `ai_video_jobs`：把「提交 → 轮询 → 转存」从渲染任务里拆出来；
3. 新表 `scene_assets`：场景四视图（按机位视角）复用池，M4-2 欠下的那半截。

全部新增，旧数据升级后 NULL / 空表，行为等价于 M4-2。

Revision ID: f1a2b3c4d5e6
Revises: a8b3c4d5e6f7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "a8b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("shots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("video_prompt", sa.Text(), nullable=True))

    op.create_table(
        "ai_video_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("shot_id", sa.String(length=36), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("provider_task_id", sa.String(length=255), nullable=True),
        sa.Column("poll_count", sa.Integer(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("video_url", sa.String(length=2048), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_video_jobs_project_created", "ai_video_jobs", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_ai_video_jobs_status_poll", "ai_video_jobs", ["status", "next_poll_at"]
    )
    op.create_index(op.f("ix_ai_video_jobs_status"), "ai_video_jobs", ["status"])

    op.create_table(
        "scene_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("scene_ref", sa.String(length=255), nullable=False),
        sa.Column("view", sa.String(length=20), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("prompt", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_scene_assets_project_scene_view",
        "scene_assets",
        ["project_id", "scene_ref", "view"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_scene_assets_project_scene_view", table_name="scene_assets")
    op.drop_table("scene_assets")
    op.drop_index(op.f("ix_ai_video_jobs_status"), table_name="ai_video_jobs")
    op.drop_index("ix_ai_video_jobs_status_poll", table_name="ai_video_jobs")
    op.drop_index("ix_ai_video_jobs_project_created", table_name="ai_video_jobs")
    op.drop_table("ai_video_jobs")
    with op.batch_alter_table("shots", schema=None) as batch_op:
        batch_op.drop_column("video_prompt")
        batch_op.drop_column("image_url")
