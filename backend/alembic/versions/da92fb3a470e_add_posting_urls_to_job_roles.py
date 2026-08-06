"""add posting_url_naukri and posting_url_linkedin to job_roles

Revision ID: da92fb3a470e
Revises: d853b6271789
Create Date: 2026-08-06 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da92fb3a470e'
down_revision: Union[str, Sequence[str], None] = 'd853b6271789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('job_roles', sa.Column('posting_url_naukri', sa.Text(), nullable=True))
    op.add_column('job_roles', sa.Column('posting_url_linkedin', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_roles', 'posting_url_linkedin')
    op.drop_column('job_roles', 'posting_url_naukri')
