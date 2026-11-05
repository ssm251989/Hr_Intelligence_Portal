"""add local_import_settings table (Part G folder-title job matching redesign)

Revision ID: c8a1f4d7e6b2
Revises: b3f8e6a2d5c9
Create Date: 2026-08-19 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a1f4d7e6b2'
down_revision: Union[str, Sequence[str], None] = 'b3f8e6a2d5c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'local_import_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ready_to_upload_root', sa.Text(), nullable=True),
        sa.Column('already_uploaded_root', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    # Singleton row -- app/local_import/service.py always reads/writes id=1. Both paths
    # start null (unconfigured) until set via the Import wizard.
    op.execute("INSERT INTO local_import_settings (id) VALUES (1)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('local_import_settings')
