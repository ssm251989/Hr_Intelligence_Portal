"""add on_hold application status and previous_status column

Revision ID: c7a1d8e4f2b6
Revises: b6e2f4a9c7d1
Create Date: 2026-08-11 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a1d8e4f2b6'
down_revision: Union[str, Sequence[str], None] = 'b6e2f4a9c7d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('applications', sa.Column('previous_status', sa.Text(), nullable=True))
    op.drop_constraint('applications_status_check', 'applications', type_='check')
    op.create_check_constraint(
        'applications_status_check',
        'applications',
        "status IN ("
        "'received','screened','hr_selected','hr_rejected',"
        "'interview_scheduled','interview_selected','interview_rejected',"
        "'salary_ok','salary_above_band','salary_approved','salary_rejected',"
        "'bgv_requested','bgv_pending','bgv_cleared','bgv_rejected',"
        "'offer_sent','onboarding_started','onboarding_completed',"
        "'on_hold')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('applications_status_check', 'applications', type_='check')
    op.create_check_constraint(
        'applications_status_check',
        'applications',
        "status IN ("
        "'received','screened','hr_selected','hr_rejected',"
        "'interview_scheduled','interview_selected','interview_rejected',"
        "'salary_ok','salary_above_band','salary_approved','salary_rejected',"
        "'bgv_requested','bgv_pending','bgv_cleared','bgv_rejected',"
        "'offer_sent','onboarding_started','onboarding_completed')",
    )
    op.drop_column('applications', 'previous_status')
