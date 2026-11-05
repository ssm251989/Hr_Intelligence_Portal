"""add hr_inbound_emails table (IMAP poll of the shared HR mailbox's inbox)

Revision ID: c3f7a9e2b5d8
Revises: b8e1d4a6f2c7
Create Date: 2026-08-22 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3f7a9e2b5d8'
down_revision: Union[str, Sequence[str], None] = 'b8e1d4a6f2c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'hr_inbound_emails',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('from_address', sa.Text(), nullable=False),
        sa.Column('to_address', sa.Text(), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message_id', sa.Text(), nullable=True),
        sa.Column('matched_candidate_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('matched_application_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['matched_candidate_id'], ['candidates.id']),
        sa.ForeignKeyConstraint(['matched_application_id'], ['applications.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )
    op.create_index(
        'ix_hr_inbound_emails_matched_candidate_id',
        'hr_inbound_emails',
        ['matched_candidate_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_hr_inbound_emails_matched_candidate_id', table_name='hr_inbound_emails')
    op.drop_table('hr_inbound_emails')
