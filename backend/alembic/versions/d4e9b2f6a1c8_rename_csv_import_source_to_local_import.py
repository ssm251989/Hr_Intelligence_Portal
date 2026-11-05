"""rename csv_import candidate source to local_import

Revision ID: d4e9b2f6a1c8
Revises: c7a1d8e4f2b6
Create Date: 2026-08-11 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e9b2f6a1c8'
down_revision: Union[str, Sequence[str], None] = 'c7a1d8e4f2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE candidates SET source = 'local_import' WHERE source = 'csv_import'")
    op.drop_constraint('candidates_source_check', 'candidates', type_='check')
    op.create_check_constraint(
        'candidates_source_check',
        'candidates',
        "source IN ('career_portal','manual','local_import','linkedin','naukri','indeed','monster','shine')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('candidates_source_check', 'candidates', type_='check')
    op.create_check_constraint(
        'candidates_source_check',
        'candidates',
        "source IN ('career_portal','manual','csv_import','linkedin','naukri','indeed','monster','shine')",
    )
    op.execute("UPDATE candidates SET source = 'csv_import' WHERE source = 'local_import'")
