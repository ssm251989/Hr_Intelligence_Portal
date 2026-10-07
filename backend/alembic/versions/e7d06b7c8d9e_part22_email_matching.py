"""part 22.2: candidate emails - which rule linked an email, suggestions when several candidates match,
sender name + reply headers, and a candidate's extra email addresses

Revision ID: e7d06b7c8d9e
Revises: d6cf5a6b7c8d
Create Date: 2026-10-07 11:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e7d06b7c8d9e'
down_revision: Union[str, Sequence[str], None] = 'd6cf5a6b7c8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hr_inbound_emails", sa.Column("from_name", sa.Text()))
    op.add_column("hr_inbound_emails", sa.Column("in_reply_to", sa.Text()))
    op.add_column("hr_inbound_emails", sa.Column("references_header", sa.Text()))
    op.add_column("hr_inbound_emails", sa.Column("match_rule", sa.Text()))  # email | alt_email | name | thread | manual
    op.add_column("hr_inbound_emails", sa.Column("match_suggestions_json", JSONB()))
    op.add_column("candidates", sa.Column("alt_emails", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column("candidates", "alt_emails")
    for col in ("match_suggestions_json", "match_rule", "references_header", "in_reply_to", "from_name"):
        op.drop_column("hr_inbound_emails", col)
