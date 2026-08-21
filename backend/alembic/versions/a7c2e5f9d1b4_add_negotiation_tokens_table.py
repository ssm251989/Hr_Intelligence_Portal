"""add negotiation_tokens table (interviewer-first scheduling negotiation)

Revision ID: a7c2e5f9d1b4
Revises: d1e6a3c9f8b4
Create Date: 2026-08-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c2e5f9d1b4'
down_revision: Union[str, Sequence[str], None] = 'd1e6a3c9f8b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'negotiation_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('interviewer_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_email', sa.Text(), nullable=False),
        sa.Column('candidate_name', sa.Text(), nullable=True),
        sa.Column('job_title', sa.Text(), nullable=True),
        sa.Column('interviewer_name', sa.Text(), nullable=True),
        sa.Column('round_day', sa.Date(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('slot_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), server_default=sa.text('60'), nullable=True),
        sa.Column('tracker_path', sa.Text(), nullable=True),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('marked_available', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('interviewer','candidate')", name='negotiation_tokens_role_check'),
        sa.CheckConstraint("kind IN ('slot','not_available','done')", name='negotiation_tokens_kind_check'),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
        sa.ForeignKeyConstraint(['interviewer_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index(
        'ix_negotiation_tokens_application_id',
        'negotiation_tokens',
        ['application_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_negotiation_tokens_application_id', table_name='negotiation_tokens')
    op.drop_table('negotiation_tokens')
