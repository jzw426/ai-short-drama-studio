"""m2: 镜头素材绑定 + 剧本台词 + 渲染幂等唯一约束

Revision ID: c3d8f2a91b57
Revises: b7c1d2e3f401
Create Date: 2026-10-26

M2「真实闭环」的结构变更：

1. `shots.video_url` —— 镜头可以绑定已上传素材。旧实现没有这个字段，渲染只能
   调付费 AI 生成视频；没有 AI Key 时链路永远出不了片（系统上线以来从未跑出过
   一条完整短剧）。
2. `scenes.dialogue` —— 台词字段。旧实现只能拿镜头"画面描述"当台词烧进画面。
3. `render_tasks` 的 `(project_id, idempotency_key)` 唯一索引 —— 旧实现是
   "先查后插"，两个并发请求（双击/重发）都能通过检查，各排一次队、各烧一遍钱。
   索引是部分索引（只约束非 NULL），保留"不传幂等键"的旧行为。
   upgrade 前先把历史重复键的旧记录置空，避免加索引直接失败。
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d8f2a91b57"
down_revision = "b7c1d2e3f401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shots", sa.Column("video_url", sa.String(length=2048), nullable=True))
    op.add_column(
        "scenes",
        sa.Column("dialogue", sa.Text(), nullable=False, server_default=""),
    )

    # 历史重复幂等键先清空（保留每个 (project, key) 下最新的一条）
    op.execute(
        sa.text(
            """
            UPDATE render_tasks SET idempotency_key = NULL
            WHERE idempotency_key IS NOT NULL AND id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY project_id, idempotency_key
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                    FROM render_tasks
                    WHERE idempotency_key IS NOT NULL
                ) ranked WHERE ranked.rn > 1
            )
            """
        )
    )
    op.create_index(
        "uq_render_tasks_project_idempotency",
        "render_tasks",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_render_tasks_project_idempotency", table_name="render_tasks")
    op.drop_column("scenes", "dialogue")
    op.drop_column("shots", "video_url")
