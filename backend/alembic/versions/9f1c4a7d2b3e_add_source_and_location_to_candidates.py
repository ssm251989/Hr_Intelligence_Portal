"""add source and location to candidates

Revision ID: 9f1c4a7d2b3e
Revises: 1c80b2e52cbe
Create Date: 2026-08-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f1c4a7d2b3e'
down_revision: Union[str, Sequence[str], None] = '1c80b2e52cbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL + a constant server_default backfills every existing row to 'manual' in the
    # same statement; the UPDATE below then re-labels the subset that actually came through
    # the careers portal, identified via the audit_log row public/router.py's submit_application
    # already writes (entity_type='candidate', action='candidate_uploaded', actor='public').
    # No existing candidate could be 'csv_import' yet -- that source doesn't exist until now.
    op.add_column(
        'candidates',
        sa.Column('source', sa.String(length=50), nullable=False, server_default='manual'),
    )
    op.create_check_constraint(
        'candidates_source_check',
        'candidates',
        "source IN ('career_portal','manual','csv_import','linkedin','naukri','indeed','monster','shine')",
    )
    op.execute(
        """
        UPDATE candidates SET source = 'career_portal'
        WHERE id IN (
            SELECT entity_id FROM audit_log
            WHERE entity_type = 'candidate' AND action = 'candidate_uploaded' AND actor = 'public'
        )
        """
    )
    op.add_column('candidates', sa.Column('location', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('candidates', 'location')
    op.drop_constraint('candidates_source_check', 'candidates', type_='check')
    op.drop_column('candidates', 'source')
