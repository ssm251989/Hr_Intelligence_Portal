"""add scheduling_method to interviews (Interviews module redesign)

Revision ID: a1b2c3d4e5f6
Revises: f1a4c7e9b3d6
Create Date: 2026-08-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a4c7e9b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default backfills every existing row to 'manual' as part of the ALTER TABLE --
    # the auto-scheduling flow (Part 3) is new, so no interview created before this migration
    # could have been scheduled any other way.
    op.add_column(
        'interviews',
        sa.Column('scheduling_method', sa.String(length=20), server_default='manual', nullable=False),
    )
    op.create_check_constraint(
        'interviews_scheduling_method_check', 'interviews', "scheduling_method IN ('manual','auto')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('interviews_scheduling_method_check', 'interviews', type_='check')
    op.drop_column('interviews', 'scheduling_method')
