"""add docusign sender to offers

Revision ID: d3f6a9b1c2e4
Revises: ba1f0e7395c5
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3f6a9b1c2e4'
down_revision: Union[str, Sequence[str], None] = 'ba1f0e7395c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('offers', sa.Column('docusign_sender_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'offers_docusign_sender_id_fkey', 'offers', 'users', ['docusign_sender_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('offers_docusign_sender_id_fkey', 'offers', type_='foreignkey')
    op.drop_column('offers', 'docusign_sender_id')
