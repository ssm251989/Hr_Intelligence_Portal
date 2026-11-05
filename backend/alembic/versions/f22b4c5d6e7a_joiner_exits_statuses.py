"""joiner exits: application statuses for dropouts / leavers, case statuses declined + exited

Revision ID: f22b4c5d6e7a
Revises: e21a3b4c5d6f
Create Date: 2026-10-05 16:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f22b4c5d6e7a'
down_revision: Union[str, Sequence[str], None] = 'e21a3b4c5d6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_OLD = ("received", "screened", "hr_selected", "hr_rejected", "interview_scheduled", "interview_selected", "interview_rejected",
           "salary_ok", "salary_above_band", "salary_approved", "salary_rejected", "bgv_requested", "bgv_pending", "bgv_cleared",
           "bgv_rejected", "offer_sent", "onboarding_started", "onboarding_completed", "on_hold")
APP_NEW = APP_OLD + ("offer_withdrawn", "offer_declined", "no_show", "left_after_joining")
CASE_OLD = ("invited", "in_progress", "ready", "joined", "no_show", "revoked")
CASE_NEW = CASE_OLD + ("declined", "exited")


def _in(values) -> str:
    return "status IN (" + ",".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint('applications_status_check', 'applications', type_='check')
    op.create_check_constraint('applications_status_check', 'applications', _in(APP_NEW))
    op.drop_constraint('preboarding_cases_status_check', 'preboarding_cases', type_='check')
    op.create_check_constraint('preboarding_cases_status_check', 'preboarding_cases', _in(CASE_NEW))


def downgrade() -> None:
    op.drop_constraint('preboarding_cases_status_check', 'preboarding_cases', type_='check')
    op.create_check_constraint('preboarding_cases_status_check', 'preboarding_cases', _in(CASE_OLD))
    op.drop_constraint('applications_status_check', 'applications', type_='check')
    op.create_check_constraint('applications_status_check', 'applications', _in(APP_OLD))
