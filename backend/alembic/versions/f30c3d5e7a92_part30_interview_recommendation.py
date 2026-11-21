"""part 30.3: each interviewer's recommendation on the interview (the hiring manager decides on the card)

Revision ID: f30c3d5e7a92
Revises: f30b2a4c6e81
Create Date: 2026-11-21 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f30c3d5e7a92'
down_revision: Union[str, Sequence[str], None] = 'f30b2a4c6e81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interviews', sa.Column('recommendation', sa.String(length=20), nullable=True))
    op.create_check_constraint('interviews_recommendation_check', 'interviews', "recommendation IN ('selected','rejected','another_round')")


def downgrade() -> None:
    op.drop_constraint('interviews_recommendation_check', 'interviews', type_='check')
    op.drop_column('interviews', 'recommendation')
