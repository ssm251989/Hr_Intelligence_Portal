"""add hr_integrations table (single shared org-level SMTP/IMAP mailbox for HR email)

Revision ID: b8e1d4a6f2c7
Revises: a7c2e5f9d1b4
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1d4a6f2c7'
down_revision: Union[str, Sequence[str], None] = 'a7c2e5f9d1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'hr_integrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('smtp_host', sa.Text(), nullable=True),
        sa.Column('smtp_port', sa.Integer(), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=True),
        sa.Column('smtp_username', sa.Text(), nullable=True),
        sa.Column('smtp_password', sa.Text(), nullable=True),
        sa.Column('from_address', sa.Text(), nullable=True),
        sa.Column('hr_module_email', sa.Text(), nullable=True),
        sa.Column('imap_host', sa.Text(), nullable=True),
        sa.Column('imap_port', sa.Integer(), nullable=True),
        sa.Column('use_ssl', sa.Boolean(), nullable=True),
        sa.Column('imap_last_uid', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('hr_integrations')
