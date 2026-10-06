"""part 21.4 / 21.5: agencies for Recruitment / BGV / Both (contact, fees, checks + prices, SLA, report format);
BGV vendor assignments (secure link, statuses, report)

Revision ID: c5be4f5a6b7c
Revises: b4ad3e4f5a6b
Create Date: 2026-10-06 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c5be4f5a6b7c'
down_revision: Union[str, Sequence[str], None] = 'b4ad3e4f5a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENCY_COLS = (("agency_type", sa.String(20), "'recruitment'"), ("contact_person", sa.Text(), None), ("phone", sa.String(50), None),
               ("address", sa.Text(), None), ("gst_pan", sa.String(50), None), ("contract_start", sa.Date(), None), ("contract_end", sa.Date(), None),
               ("fee_type", sa.String(20), None), ("fee_value", sa.Numeric(), None), ("payment_terms", sa.Text(), None),
               ("turnaround_days", sa.Integer(), None), ("report_format", sa.Text(), None))


def upgrade() -> None:
    for name, type_, default in AGENCY_COLS:
        op.add_column('recruitment_agencies', sa.Column(name, type_, nullable=default is None, server_default=sa.text(default) if default else None))
    op.add_column('recruitment_agencies', sa.Column('bgv_checks_json', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint('recruitment_agencies_type_check', 'recruitment_agencies', "agency_type IN ('recruitment','bgv','both')")
    op.create_table(
        'bgv_assignments',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('application_id', UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agency_id', UUID(as_uuid=True), sa.ForeignKey('recruitment_agencies.id'), nullable=False, index=True),
        sa.Column('checks_json', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('due_date', sa.Date()),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'assigned'")),
        sa.Column('token', sa.Text(), nullable=False, unique=True),
        sa.Column('link_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True)),
        sa.Column('report_path', sa.Text()),
        sa.Column('report_name', sa.Text()),
        sa.Column('report_note', sa.Text()),
        sa.Column('report_uploaded_at', sa.DateTime(timezone=True)),
        sa.Column('decision', sa.String(20)),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
        sa.Column('cost', sa.Numeric()),
        sa.Column('reminders_json', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('cancelled_at', sa.DateTime(timezone=True)),
        sa.Column('cancel_reason', sa.Text()),
        sa.Column('created_by', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.CheckConstraint("status IN ('assigned','in_progress','report_received','decided','cancelled')", name='bgv_assignments_status_check'),
    )
    enable_rls(op, 'bgv_assignments')


def downgrade() -> None:
    disable_rls(op, 'bgv_assignments')
    op.drop_table('bgv_assignments')
    op.drop_constraint('recruitment_agencies_type_check', 'recruitment_agencies', type_='check')
    op.drop_column('recruitment_agencies', 'bgv_checks_json')
    for name, _t, _d in reversed(AGENCY_COLS):
        op.drop_column('recruitment_agencies', name)
