"""add scan_interval_minutes to local_import_settings (Part G interval configurability)

Revision ID: d9e4c1a8f3b7
Revises: c8a1f4d7e6b2
Create Date: 2026-08-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e4c1a8f3b7'
down_revision: Union[str, Sequence[str], None] = 'c8a1f4d7e6b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('local_import_settings', sa.Column('scan_interval_minutes', sa.Integer(), nullable=True))
    # 30 preserves the previously-hardcoded interval for every existing install.
    op.execute("UPDATE local_import_settings SET scan_interval_minutes = 30 WHERE scan_interval_minutes IS NULL")
    op.alter_column('local_import_settings', 'scan_interval_minutes', nullable=False, server_default='30')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('local_import_settings', 'scan_interval_minutes')
