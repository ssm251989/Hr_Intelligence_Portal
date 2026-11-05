"""part 26: HR Autopilot -- agent_activity (what the automatic agents did) + autopilot_state (event cursor etc.)

Revision ID: c6a8e2f4b1d3
Revises: a9f28d9eafb0
Create Date: 2026-11-02 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c6a8e2f4b1d3'
down_revision: Union[str, Sequence[str], None] = 'a9f28d9eafb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENTS = "('watchdog','screening','sourcing','salary','documents','bgv','offer','onboarding','exit','briefing')"


def upgrade() -> None:
    op.create_table(
        'agent_activity',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('agent', sa.String(20), nullable=False),
        sa.Column('trigger', sa.String(10), nullable=False),
        sa.Column('event', sa.String(100)),
        sa.Column('action', sa.String(60), nullable=False),
        sa.Column('outcome', sa.String(10), nullable=False),
        sa.Column('rule', sa.String(100)),
        sa.Column('entity_type', sa.String(50)),
        sa.Column('entity_id', UUID(as_uuid=True)),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('details', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.CheckConstraint(f"agent IN {AGENTS}", name='agent_activity_agent_check'),
        sa.CheckConstraint("outcome IN ('done','decided','proposed','escalated','skipped','failed')", name='agent_activity_outcome_check'),
        sa.CheckConstraint("trigger IN ('event','schedule','manual')", name='agent_activity_trigger_check'),
    )
    op.create_index('ix_agent_activity_created_at', 'agent_activity', ['created_at'])
    op.create_index('ix_agent_activity_entity', 'agent_activity', ['entity_type', 'entity_id', 'action'])
    enable_rls(op, 'agent_activity')
    op.create_table(
        'autopilot_state',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value_json', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'key', name='autopilot_state_tenant_key_uq'),
    )
    enable_rls(op, 'autopilot_state')


def downgrade() -> None:
    disable_rls(op, 'autopilot_state')
    op.drop_table('autopilot_state')
    disable_rls(op, 'agent_activity')
    op.drop_index('ix_agent_activity_entity', 'agent_activity')
    op.drop_index('ix_agent_activity_created_at', 'agent_activity')
    op.drop_table('agent_activity')
