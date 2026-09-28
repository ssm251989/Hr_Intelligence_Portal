"""part18 candidate tags

Revision ID: c9e4a2d8f6b1
Revises: b7d3f1a9c5e2
Create Date: 2026-09-28 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c9e4a2d8f6b1'
down_revision: Union[str, Sequence[str], None] = 'b7d3f1a9c5e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('tags', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False))
    op.create_index('ix_candidates_tags', 'candidates', ['tags'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_candidates_tags', table_name='candidates')
    op.drop_column('candidates', 'tags')
