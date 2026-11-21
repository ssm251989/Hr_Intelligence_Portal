"""part 30.2: public APIs + webhooks (api_keys, api_usage, webhook_subscriptions, webhook_deliveries)

Revision ID: f30b2a4c6e81
Revises: f30a1b2c3d4e
Create Date: 2026-11-20 19:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'f30b2a4c6e81'
down_revision: Union[str, Sequence[str], None] = 'f30a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("webhook_deliveries", "webhook_subscriptions", "api_usage", "api_keys")
PERMISSION = "platform.api_keys.manage"


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('prefix', sa.String(length=24), nullable=False),
        sa.Column('secret_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('mode', sa.String(length=4), server_default=sa.text("'live'"), nullable=False),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("mode IN ('live', 'test')", name='api_keys_mode_check'),
    )
    op.create_index('ix_api_keys_prefix', 'api_keys', ['prefix'], unique=True)
    op.create_index(op.f('ix_api_keys_tenant_id'), 'api_keys', ['tenant_id'], unique=False)

    op.create_table(
        'api_usage',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('api_key_id', sa.UUID(), sa.ForeignKey('api_keys.id', ondelete='CASCADE'), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('endpoint', sa.String(length=200), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_usage_key_created', 'api_usage', ['api_key_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_api_usage_tenant_id'), 'api_usage', ['tenant_id'], unique=False)

    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('events', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_subscriptions_tenant_id'), 'webhook_subscriptions', ['tenant_id'], unique=False)

    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('subscription_id', sa.UUID(), sa.ForeignKey('webhook_subscriptions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event', sa.String(length=60), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=10), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_status', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name='webhook_deliveries_status_check'),
    )
    op.create_index('ix_webhook_deliveries_due', 'webhook_deliveries', ['status', 'next_at'], unique=False)
    op.create_index('ix_webhook_deliveries_sub_created', 'webhook_deliveries', ['subscription_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_tenant_id'), 'webhook_deliveries', ['tenant_id'], unique=False)

    for table in reversed(TABLES):
        enable_rls(op, table)
    # the Super Admin system role ("*") picks the new permission up on its next sync; add it now so the
    # Developers page works for existing companies without waiting for that
    op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{PERMISSION}') "
               f"WHERE is_system AND name = 'Super Admin' AND NOT ('{PERMISSION}' = ANY(permissions))")


def downgrade() -> None:
    op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{PERMISSION}') WHERE is_system AND name = 'Super Admin'")
    for table in TABLES:
        disable_rls(op, table)
        op.drop_table(table)
