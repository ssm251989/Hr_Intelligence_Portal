"""add suitable_job_id and suitable_job_score to candidates

Revision ID: f4b7d1e9c3a6
Revises: e1f3a7c9b2d4
Create Date: 2026-08-12 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4b7d1e9c3a6'
down_revision: Union[str, Sequence[str], None] = 'e1f3a7c9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('suitable_job_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'candidates_suitable_job_id_fkey', 'candidates', 'job_roles', ['suitable_job_id'], ['id']
    )
    op.add_column('candidates', sa.Column('suitable_job_score', sa.Numeric(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('candidates', 'suitable_job_score')
    op.drop_constraint('candidates_suitable_job_id_fkey', 'candidates', type_='foreignkey')
    op.drop_column('candidates', 'suitable_job_id')
