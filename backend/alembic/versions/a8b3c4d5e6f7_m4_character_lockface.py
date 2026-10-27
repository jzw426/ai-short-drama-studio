"""M4-2 角色一致性：角色卡（锁脸）字段

新增四列：
- reference_image_url：锁脸基准图（规范 URL）
- image_seed：出图种子，同一角色复用
- visual_prompt：结构化外观描述
- view_images：三视图 {"front"/"side"/"full"/"back": url}

可空、无默认值约束外溢：旧数据升级后这些列全为 NULL，路由按"未锁脸"处理。

Revision ID: a8b3c4d5e6f7
Revises: e5a7c1d9f206
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a8b3c4d5e6f7"
down_revision: Union[str, None] = "e5a7c1d9f206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reference_image_url", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("image_seed", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("visual_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("view_images", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("view_images")
        batch_op.drop_column("visual_prompt")
        batch_op.drop_column("image_seed")
        batch_op.drop_column("reference_image_url")
