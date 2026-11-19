"""part 29: a card whose step was already done another way is closed ("closed" status + reason)

Revision ID: b4d7e9a1c3f5
Revises: e1f4a7c2d9b8
Create Date: 2026-11-19 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b4d7e9a1c3f5'
down_revision: Union[str, Sequence[str], None] = 'e1f4a7c2d9b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "('pending','approved','edited','rejected')"
NEW = "('pending','approved','edited','rejected','closed')"


def upgrade() -> None:
    op.add_column('agent_suggestions', sa.Column('closed_reason', sa.Text(), nullable=True))
    op.drop_constraint('agent_suggestions_status_check', 'agent_suggestions', type_='check')
    op.create_check_constraint('agent_suggestions_status_check', 'agent_suggestions', f"status IN {NEW}")


def downgrade() -> None:
    # a closed card was never decided; going back it is shown as rejected (nothing was applied either way)
    op.execute("UPDATE agent_suggestions SET status = 'rejected' WHERE status = 'closed'")
    op.drop_constraint('agent_suggestions_status_check', 'agent_suggestions', type_='check')
    op.create_check_constraint('agent_suggestions_status_check', 'agent_suggestions', f"status IN {OLD}")
    op.drop_column('agent_suggestions', 'closed_reason')
