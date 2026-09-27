"""part17 idempotency keys

Revision ID: c3f7a1d9e5b2
Revises: b8e4c2f6a9d3
Create Date: 2026-09-27 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c3f7a1d9e5b2'
down_revision: Union[str, Sequence[str], None] = 'b8e4c2f6a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('idempotency_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'key', name='idempotency_keys_key_uq')
    )
    op.create_index(op.f('ix_idempotency_keys_tenant_id'), 'idempotency_keys', ['tenant_id'], unique=False)
    enable_rls(op, "idempotency_keys")


def downgrade() -> None:
    disable_rls(op, "idempotency_keys")
    op.drop_table('idempotency_keys')
