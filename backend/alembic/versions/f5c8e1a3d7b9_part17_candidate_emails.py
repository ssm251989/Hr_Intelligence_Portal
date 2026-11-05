"""part17 candidate emails triage

Revision ID: f5c8e1a3d7b9
Revises: e3b7d2f9a1c6
Create Date: 2026-09-27 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f5c8e1a3d7b9'
down_revision: Union[str, Sequence[str], None] = 'e3b7d2f9a1c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hr_inbound_emails', sa.Column('topic', sa.Text(), nullable=True))
    op.add_column('hr_inbound_emails', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('hr_inbound_emails', sa.Column('summary_source', sa.Text(), nullable=True))
    op.add_column('hr_inbound_emails', sa.Column('status', sa.Text(), server_default=sa.text("'needs_action'"), nullable=False))
    op.add_column('hr_inbound_emails', sa.Column('done_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hr_inbound_emails', sa.Column('done_by', sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ('done_by', 'done_at', 'status', 'summary_source', 'summary', 'topic'):
        op.drop_column('hr_inbound_emails', col)
