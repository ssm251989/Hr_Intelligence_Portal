"""part 20.4: the interviewer's answer to a booked interview -- declined (reason) or a new time proposed

Revision ID: a39c2d3e4f5a
Revises: f28b1c2d3e4f
Create Date: 2026-10-06 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a39c2d3e4f5a'
down_revision: Union[str, Sequence[str], None] = 'f28b1c2d3e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interviews', sa.Column('interviewer_response_json', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('interviews', 'interviewer_response_json')
