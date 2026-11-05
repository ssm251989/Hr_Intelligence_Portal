"""part 20.3: employee self-service -- profile change requests (HR approves); resignation: early release, resignation
letter, manager approval step

Revision ID: f28b1c2d3e4f
Revises: e27a9b0c1d2f
Create Date: 2026-10-06 19:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'f28b1c2d3e4f'
down_revision: Union[str, Sequence[str], None] = 'e27a9b0c1d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'employee_change_requests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('employee_id', UUID(as_uuid=True), sa.ForeignKey('employees.id'), nullable=False, index=True),
        sa.Column('requested_by', sa.Text()),
        sa.Column('changes_json', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('note', sa.Text()),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('reviewed_by', sa.Text()),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('review_note', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name='employee_change_requests_status_check'),
    )
    enable_rls(op, 'employee_change_requests')
    op.add_column('separations', sa.Column('early_release_requested', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('separations', sa.Column('resignation_letter_ref', sa.Text(), nullable=True))
    op.add_column('separations', sa.Column('manager_approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('separations', sa.Column('manager_approved_by', sa.Text(), nullable=True))
    op.add_column('separations', sa.Column('manager_note', sa.Text(), nullable=True))


def downgrade() -> None:
    for c in ('manager_note', 'manager_approved_by', 'manager_approved_at', 'resignation_letter_ref', 'early_release_requested'):
        op.drop_column('separations', c)
    disable_rls(op, 'employee_change_requests')
    op.drop_table('employee_change_requests')
