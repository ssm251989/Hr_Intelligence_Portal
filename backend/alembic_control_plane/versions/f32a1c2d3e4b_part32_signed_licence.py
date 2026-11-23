"""part 32: signed CTD approvals - licence_approvals, request kind / nonce / text, install id, upgrade grace

Revision ID: f32a1c2d3e4b
Revises: e28a5b6c7d8f
Create Date: 2026-11-21 18:00:00

Existing companies (this upgrade) are recorded for the 14-day grace: they keep working with a banner
"Ask CTD Techs for your approval code" until CTD's signed approval is entered. Companies created later get no grace.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f32a1c2d3e4b'
down_revision: Union[str, Sequence[str], None] = 'e28a5b6c7d8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'licence_approvals',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('nonce', sa.String(length=64), nullable=False),
        sa.Column('request_number', sa.String(length=20), nullable=True),
        sa.Column('entered_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nonce', name='licence_approvals_nonce_uq'),
        sa.CheckConstraint("kind IN ('access','modules')", name='licence_approvals_kind_check'),
    )
    op.create_index('ix_licence_approvals_tenant', 'licence_approvals', ['tenant_id', 'created_at'])
    op.add_column('activation_requests', sa.Column('kind', sa.String(length=10), server_default=sa.text("'modules'"), nullable=False))
    op.add_column('activation_requests', sa.Column('nonce', sa.String(length=64), nullable=True))
    op.add_column('activation_requests', sa.Column('request_text', sa.Text(), nullable=True))
    op.alter_column('activation_requests', 'code_hash', existing_type=sa.Text(), nullable=True)

    conn = op.get_bind()
    now = datetime.now(timezone.utc).isoformat()
    tenants = [str(r[0]) for r in conn.execute(sa.text("SELECT id FROM tenants WHERE status NOT IN ('deleted', 'archived')"))]
    for key, value in (("licence.install_id", {"id": str(uuid.uuid4())}), ("licence.grace", {"started_at": now, "tenants": tenants})):
        conn.execute(sa.text("INSERT INTO platform_config (key, value_json, updated_by) VALUES (:k, CAST(:v AS jsonb), 'part-32 upgrade') "
                             "ON CONFLICT (key) DO NOTHING"), {"k": key, "v": json.dumps(value)})


def downgrade() -> None:
    op.execute("DELETE FROM platform_config WHERE key IN ('licence.install_id', 'licence.grace')")
    op.alter_column('activation_requests', 'code_hash', existing_type=sa.Text(), nullable=False)
    op.drop_column('activation_requests', 'request_text')
    op.drop_column('activation_requests', 'nonce')
    op.drop_column('activation_requests', 'kind')
    op.drop_index('ix_licence_approvals_tenant', table_name='licence_approvals')
    op.drop_table('licence_approvals')
