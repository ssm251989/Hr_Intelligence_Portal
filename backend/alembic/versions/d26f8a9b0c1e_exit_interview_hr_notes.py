"""fix 2026-10-06: exit interview moved to the employee -- HR's private notes kept apart from the answers

Revision ID: d26f8a9b0c1e
Revises: c25e7f8a9b0d
Create Date: 2026-10-06 15:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd26f8a9b0c1e'
down_revision: Union[str, Sequence[str], None] = 'c25e7f8a9b0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('separations', sa.Column('exit_interview_hr_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('separations', 'exit_interview_hr_notes')
