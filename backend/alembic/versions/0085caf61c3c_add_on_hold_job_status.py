"""add on_hold job status

Revision ID: 0085caf61c3c
Revises: 657d1ad71dcc
Create Date: 2026-08-09 13:41:37.560048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0085caf61c3c'
down_revision: Union[str, Sequence[str], None] = '657d1ad71dcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('job_roles_status_check', 'job_roles', type_='check')
    op.create_check_constraint(
        'job_roles_status_check',
        'job_roles',
        "status IN ('draft','ready_for_publishing','published','closed','on_hold')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('job_roles_status_check', 'job_roles', type_='check')
    op.create_check_constraint(
        'job_roles_status_check',
        'job_roles',
        "status IN ('draft','ready_for_publishing','published','closed')",
    )
