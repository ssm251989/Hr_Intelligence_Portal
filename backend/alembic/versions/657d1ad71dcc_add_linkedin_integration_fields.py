"""add linkedin integration fields (user_integrations.expires_at/provider_metadata, job_roles.linkedin_post_urn)

Revision ID: 657d1ad71dcc
Revises: da92fb3a470e
Create Date: 2026-08-06 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '657d1ad71dcc'
down_revision: Union[str, Sequence[str], None] = 'da92fb3a470e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_integrations', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'user_integrations',
        sa.Column(
            'provider_metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column('job_roles', sa.Column('linkedin_post_urn', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_roles', 'linkedin_post_urn')
    op.drop_column('user_integrations', 'provider_metadata')
    op.drop_column('user_integrations', 'expires_at')
