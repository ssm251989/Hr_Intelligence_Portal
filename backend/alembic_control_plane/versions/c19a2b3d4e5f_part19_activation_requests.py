"""part19 module activation requests + platform config

Revision ID: c19a2b3d4e5f
Revises: f3c64b202978
Create Date: 2026-10-03 22:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c19a2b3d4e5f'
down_revision: Union[str, Sequence[str], None] = 'f3c64b202978'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('activation_requests',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('modules', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('company_name', sa.Text(), nullable=True),
    sa.Column('domain', sa.Text(), nullable=True),
    sa.Column('requested_by_name', sa.Text(), nullable=True),
    sa.Column('requested_by_email', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('emailed_to', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('email_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_by', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('pending','activated','expired','cancelled','replaced')", name='activation_requests_status_check'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activation_requests_tenant_id'), 'activation_requests', ['tenant_id'], unique=False)
    op.create_table('platform_config',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('platform_config')
    op.drop_index(op.f('ix_activation_requests_tenant_id'), table_name='activation_requests')
    op.drop_table('activation_requests')
