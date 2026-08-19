"""add interview_confirmation_tokens table (Part 3 -- email + secure-link confirmation)

Revision ID: f1a4c7e9b3d6
Revises: e2f5b8c1a9d3
Create Date: 2026-08-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a4c7e9b3d6'
down_revision: Union[str, Sequence[str], None] = 'e2f5b8c1a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'interview_confirmation_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('candidate_name', sa.Text(), nullable=True),
        sa.Column('job_title', sa.Text(), nullable=True),
        sa.Column('interviewer_name', sa.Text(), nullable=True),
        sa.Column('interviewer_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('slot_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), server_default=sa.text('60'), nullable=True),
        sa.Column('tracker_path', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
        sa.ForeignKeyConstraint(['interviewer_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index(
        'ix_interview_confirmation_tokens_application_id',
        'interview_confirmation_tokens',
        ['application_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_interview_confirmation_tokens_application_id', table_name='interview_confirmation_tokens')
    op.drop_table('interview_confirmation_tokens')
