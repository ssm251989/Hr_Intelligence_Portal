"""add audit_log index on entity_type, entity_id, created_at

Revision ID: a7d2e5c8b4f1
Revises: f4b7d1e9c3a6
Create Date: 2026-08-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7d2e5c8b4f1'
down_revision: Union[str, Sequence[str], None] = 'f4b7d1e9c3a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_audit_log_entity_type_entity_id_created_at",
        "audit_log",
        ["entity_type", "entity_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_log_entity_type_entity_id_created_at", table_name="audit_log")
