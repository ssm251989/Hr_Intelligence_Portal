"""part17 salary check

Revision ID: e3b7d2f9a1c6
Revises: d9a4c1e7b2f5
Create Date: 2026-09-27 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e3b7d2f9a1c6'
down_revision: Union[str, Sequence[str], None] = 'd9a4c1e7b2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('salary_check', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'salary_check')
