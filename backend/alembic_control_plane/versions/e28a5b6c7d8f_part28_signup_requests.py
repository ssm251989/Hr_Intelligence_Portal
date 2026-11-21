"""part 28.5: cloud sign-up requests ("Create your company")

Revision ID: e28a5b6c7d8f
Revises: d19b2c3e4f5a
Create Date: 2026-11-20 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e28a5b6c7d8f'
down_revision: Union[str, Sequence[str], None] = 'd19b2c3e4f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = "('pending_email','confirmed','provisioning','waiting_approval','active','failed','expired')"


def upgrade() -> None:
    op.create_table(
        'signup_requests',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('company_name', sa.Text(), nullable=False),
        sa.Column('slug', sa.String(length=63), nullable=False),
        sa.Column('admin_name', sa.Text(), nullable=False),
        sa.Column('admin_email', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('modules', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending_email'"), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint(f"status IN {STATUSES}", name='signup_requests_status_check'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_signup_requests_slug', 'signup_requests', ['slug'])
    op.create_index('ix_signup_requests_admin_email', 'signup_requests', ['admin_email'])


def downgrade() -> None:
    op.drop_index('ix_signup_requests_admin_email', table_name='signup_requests')
    op.drop_index('ix_signup_requests_slug', table_name='signup_requests')
    op.drop_table('signup_requests')
