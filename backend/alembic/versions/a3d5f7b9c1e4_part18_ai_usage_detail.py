"""part18 AI usage detail (user, module, what it was for, status, latency)

Revision ID: a3d5f7b9c1e4
Revises: f9b1d3e5a7c2
Create Date: 2026-09-28 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3d5f7b9c1e4'
down_revision: Union[str, Sequence[str], None] = 'f9b1d3e5a7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_usage_records', sa.Column('module', sa.String(length=50), nullable=True))
    op.add_column('ai_usage_records', sa.Column('user_id', sa.UUID(), nullable=True))
    op.add_column('ai_usage_records', sa.Column('entity_type', sa.String(length=50), nullable=True))
    op.add_column('ai_usage_records', sa.Column('entity_id', sa.UUID(), nullable=True))
    op.add_column('ai_usage_records', sa.Column('status', sa.String(length=20), server_default=sa.text("'ok'"), nullable=False))
    op.add_column('ai_usage_records', sa.Column('latency_ms', sa.Integer(), nullable=True))
    op.create_index('ix_ai_usage_records_tenant_created', 'ai_usage_records', ['tenant_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_usage_records_tenant_created', table_name='ai_usage_records')
    for c in ('latency_ms', 'status', 'entity_id', 'entity_type', 'user_id', 'module'):
        op.drop_column('ai_usage_records', c)
