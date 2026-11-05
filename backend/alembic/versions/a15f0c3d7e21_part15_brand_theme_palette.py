"""part15 brand theme palette (Fresh design tokens per tenant)

Revision ID: a15f0c3d7e21
Revises: 45ed086dca28
Create Date: 2026-09-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a15f0c3d7e21'
down_revision: Union[str, Sequence[str], None] = '45ed086dca28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Part 15 A: optional per-tenant overrides of the "Fresh" design tokens,
    # {"light": {"brand": "#..", ...}, "dark": {...}}. Empty = the default theme.
    op.add_column('brand_themes', sa.Column('palette_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('brand_themes', 'palette_json')
