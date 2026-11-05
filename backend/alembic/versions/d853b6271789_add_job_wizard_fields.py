"""add job wizard fields (benefits, additional_notes, published_platforms, publish_settings)

Revision ID: d853b6271789
Revises: d3f6a9b1c2e4
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd853b6271789'
down_revision: Union[str, Sequence[str], None] = 'd3f6a9b1c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('job_roles', sa.Column('benefits', sa.Text(), nullable=True))
    op.add_column('job_roles', sa.Column('additional_notes', sa.Text(), nullable=True))
    op.add_column(
        'job_roles',
        sa.Column(
            'published_platforms',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        'job_roles',
        sa.Column(
            'publish_settings',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_roles', 'publish_settings')
    op.drop_column('job_roles', 'published_platforms')
    op.drop_column('job_roles', 'additional_notes')
    op.drop_column('job_roles', 'benefits')
