"""part18 users.deactivated_at

Revision ID: f9b1d3e5a7c2
Revises: e7a3c9f1b5d2
Create Date: 2026-09-28 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f9b1d3e5a7c2'
down_revision: Union[str, Sequence[str], None] = 'e7a3c9f1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'deactivated_at')
