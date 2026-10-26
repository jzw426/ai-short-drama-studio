"""add ai_usage table

Revision ID: cef2afd76e33
Revises: e246b1a03921
Create Date: 2026-09-23 18:35:06.210974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cef2afd76e33'
down_revision: Union[str, None] = 'e246b1a03921'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_usage',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='uq_ai_usage_user_date'),
    )
    op.create_index(op.f('ix_ai_usage_date'), 'ai_usage', ['date'], unique=False)
    op.create_index(op.f('ix_ai_usage_user_id'), 'ai_usage', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_usage_user_id'), table_name='ai_usage')
    op.drop_index(op.f('ix_ai_usage_date'), table_name='ai_usage')
    op.drop_table('ai_usage')
