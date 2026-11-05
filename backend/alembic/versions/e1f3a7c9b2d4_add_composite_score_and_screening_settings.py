"""add composite_score to applications and screening_settings table

Revision ID: e1f3a7c9b2d4
Revises: d4e9b2f6a1c8
Create Date: 2026-08-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f3a7c9b2d4'
down_revision: Union[str, Sequence[str], None] = 'd4e9b2f6a1c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('applications', sa.Column('composite_score', sa.Numeric(), nullable=True))

    op.create_table(
        'screening_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dashboard_min_score', sa.Numeric(), nullable=False, server_default='60'),
        sa.Column('dashboard_max_score', sa.Numeric(), nullable=False, server_default='100'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    # Singleton row -- app/screening/service.py always reads/writes id=1.
    op.execute(
        "INSERT INTO screening_settings (id, dashboard_min_score, dashboard_max_score) "
        "VALUES (1, 60, 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('screening_settings')
    op.drop_column('applications', 'composite_score')
