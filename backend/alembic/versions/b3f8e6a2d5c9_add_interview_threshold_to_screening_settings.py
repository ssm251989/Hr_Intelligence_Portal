"""add interview_min_score/interview_max_score to screening_settings (Part F)

Revision ID: b3f8e6a2d5c9
Revises: a7d2e5c8b4f1
Create Date: 2026-08-18 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f8e6a2d5c9'
down_revision: Union[str, Sequence[str], None] = 'a7d2e5c8b4f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A second, independent min/max pair -- Part F's own Screening -> Interview readiness
    # threshold, deliberately separate from dashboard_min_score/dashboard_max_score (Part
    # D's received -> screened auto-advance threshold). 75/100 seeded as a stricter bar
    # than Part D's 60/100 default: "ready for interview" is a higher signal than merely
    # "worth screening in."
    op.add_column('screening_settings', sa.Column('interview_min_score', sa.Numeric(), nullable=True))
    op.add_column('screening_settings', sa.Column('interview_max_score', sa.Numeric(), nullable=True))
    op.execute("UPDATE screening_settings SET interview_min_score = 75, interview_max_score = 100 WHERE id = 1")
    op.alter_column('screening_settings', 'interview_min_score', nullable=False, server_default='75')
    op.alter_column('screening_settings', 'interview_max_score', nullable=False, server_default='100')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('screening_settings', 'interview_max_score')
    op.drop_column('screening_settings', 'interview_min_score')
