"""part 22.3: candidate emails remember when HR first opened them (unread ones are bold in My approvals)

Revision ID: f8e17c8d9eaf
Revises: e7d06b7c8d9e
Create Date: 2026-10-07 11:40:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f8e17c8d9eaf'
down_revision: Union[str, Sequence[str], None] = 'e7d06b7c8d9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hr_inbound_emails", sa.Column("read_at", sa.DateTime(timezone=True)))
    op.add_column("hr_inbound_emails", sa.Column("read_by", sa.Text()))
    op.execute("UPDATE hr_inbound_emails SET read_at = coalesce(done_at, created_at), read_by = 'before 22.3' WHERE status = 'done'")


def downgrade() -> None:
    op.drop_column("hr_inbound_emails", "read_by")
    op.drop_column("hr_inbound_emails", "read_at")
