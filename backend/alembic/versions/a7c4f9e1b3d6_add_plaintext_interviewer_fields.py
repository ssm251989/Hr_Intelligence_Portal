"""add plain-text interviewer name/email to negotiation_tokens and interviews

The interviewer-first negotiation flow (app/interview_scheduling/negotiation.py) no longer
requires a pool interviewer to resolve to a registered User account -- the Interviewer Pool
sheet's Mails tab is the sole source of an interviewer's reachable email address, and the
shared HR mailbox is what actually sends every email. That means interviewer_user_id (a FK
to users.id) can no longer be relied on to carry the interviewer's email through to
_finalize's confirmation step, nor to attribute a finalized Interview to anyone in
reports/list views once interviewer_id is left NULL for a non-User interviewer.

negotiation_tokens.interviewer_email: the Mails-sheet address captured at offer-send time,
carried forward through the candidate round so _finalize can send the final .ics
confirmation without a User lookup.

interviews.interviewer_name / interviews.interviewer_email: set by _finalize on every
confirmed interview (regardless of whether interviewer_id also ends up set), so the
Interview List/Dashboard and interviewer-workload report can always show who it was even
when there's no User row to join against.

Revision ID: a7c4f9e1b3d6
Revises: 05d5c042ecb1
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c4f9e1b3d6'
down_revision: Union[str, Sequence[str], None] = '05d5c042ecb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('negotiation_tokens', sa.Column('interviewer_email', sa.Text(), nullable=True))
    op.add_column('interviews', sa.Column('interviewer_name', sa.Text(), nullable=True))
    op.add_column('interviews', sa.Column('interviewer_email', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('interviews', 'interviewer_email')
    op.drop_column('interviews', 'interviewer_name')
    op.drop_column('negotiation_tokens', 'interviewer_email')
