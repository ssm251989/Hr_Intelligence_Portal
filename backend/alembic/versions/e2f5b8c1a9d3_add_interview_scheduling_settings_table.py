"""add interview_scheduling_settings table (Interview Scheduling automation foundation)

Revision ID: e2f5b8c1a9d3
Revises: d9e4c1a8f3b7
Create Date: 2026-08-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f5b8c1a9d3'
down_revision: Union[str, Sequence[str], None] = 'd9e4c1a8f3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'interview_scheduling_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tracker_path', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    # Singleton row -- app/interview_scheduling/storage.py always reads/writes id=1.
    # Starts null (unconfigured) until set via the Settings page.
    op.execute("INSERT INTO interview_scheduling_settings (id) VALUES (1)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('interview_scheduling_settings')
