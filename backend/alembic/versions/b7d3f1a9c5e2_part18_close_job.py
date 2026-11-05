"""part18 close a job (reason, hold applications)

Revision ID: b7d3f1a9c5e2
Revises: a1c5e8f3d7b2
Create Date: 2026-09-28 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7d3f1a9c5e2'
down_revision: Union[str, Sequence[str], None] = 'a1c5e8f3d7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('hold_reason', sa.Text(), nullable=True))
    op.add_column('job_roles', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('job_roles', sa.Column('close_reason', sa.String(length=30), nullable=True))
    op.add_column('job_roles', sa.Column('close_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_roles', 'close_note')
    op.drop_column('job_roles', 'close_reason')
    op.drop_column('job_roles', 'closed_at')
    op.drop_column('applications', 'hold_reason')
