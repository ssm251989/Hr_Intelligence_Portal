"""add job_type to job_roles

Revision ID: 1c80b2e52cbe
Revises: 0085caf61c3c
Create Date: 2026-08-09 14:49:16.613402

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c80b2e52cbe'
down_revision: Union[str, Sequence[str], None] = '0085caf61c3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL + a constant server_default backfills every existing row to 'Full-time'
    # in the same statement -- no separate UPDATE needed, and no existing job breaks.
    op.add_column(
        'job_roles',
        sa.Column('job_type', sa.String(length=50), nullable=False, server_default='Full-time'),
    )
    op.create_check_constraint(
        'job_roles_job_type_check',
        'job_roles',
        "job_type IN ('Full-time','Part-time','Contract')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('job_roles_job_type_check', 'job_roles', type_='check')
    op.drop_column('job_roles', 'job_type')
