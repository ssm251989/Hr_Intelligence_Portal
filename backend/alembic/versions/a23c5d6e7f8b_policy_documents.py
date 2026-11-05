"""policies & handbook: file, category, version, effective date and processing status on knowledge_documents

Revision ID: a23c5d6e7f8b
Revises: f22b4c5d6e7a
Create Date: 2026-10-05 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'a23c5d6e7f8b'
down_revision: Union[str, Sequence[str], None] = 'f22b4c5d6e7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("category", sa.String(30)), ("version", sa.String(30)), ("effective_date", sa.Date()),
    ("file_path", sa.Text()), ("file_name", sa.Text()), ("content_type", sa.String(120)), ("size_bytes", sa.Integer()),
    ("error", sa.Text()), ("processed_at", sa.DateTime(timezone=True)), ("replaces_id", UUID(as_uuid=True)),
    ("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column('knowledge_documents', sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column('knowledge_documents', name)
