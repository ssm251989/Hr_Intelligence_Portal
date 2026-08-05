"""add google calendar integration

Revision ID: ba1f0e7395c5
Revises: 7b0e8b9108aa
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ba1f0e7395c5'
down_revision: Union[str, Sequence[str], None] = '7b0e8b9108aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='user_integrations_user_id_provider_key'),
    )
    op.add_column('interviews', sa.Column('calendar_event_id', sa.String(length=255), nullable=True))
    op.add_column('interviews', sa.Column('calendar_link', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('interviews', 'calendar_link')
    op.drop_column('interviews', 'calendar_event_id')
    op.drop_table('user_integrations')
