"""audit_log.created_at: use clock_timestamp() instead of now() as the server default

now() (== CURRENT_TIMESTAMP == transaction_timestamp()) is frozen for the entire duration
of a Postgres transaction -- every row inserted within one transaction gets the exact same
created_at. That's invisible for the vast majority of this app's usage (each HTTP request
is its own short-lived transaction, and log_action's own db.commit() ends one and starts the
next), but breaks any logic that needs to tell apart the ORDER of two audit_log rows
inserted within the same transaction -- which is exactly what
app.interview_scheduling.negotiation._is_flagged_for_manual_scheduling now does (comparing
interview_negotiation_manual_scheduling_required against the newer
interview_negotiation_manual_scheduling_cleared entry retry_negotiation logs, both within
one request's transaction). clock_timestamp() returns the actual wall-clock time at each
individual call, monotonically increasing regardless of transaction boundaries, so "most
recent relevant entry" queries are reliable everywhere this pattern is used, present or
future.

Revision ID: 05d5c042ecb1
Revises: b3d8f1a6c9e2
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05d5c042ecb1'
down_revision: Union[str, Sequence[str], None] = 'b3d8f1a6c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('audit_log', 'created_at', server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('audit_log', 'created_at', server_default=sa.text("now()"))
