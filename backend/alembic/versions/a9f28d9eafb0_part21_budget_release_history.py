"""part 21.7: budget released back to finance -- how much, when and why (exit pro-rata / full, drop-outs)

Revision ID: a9f28d9eafb0
Revises: f8e17c8d9eaf
Create Date: 2026-10-07 14:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a9f28d9eafb0'
down_revision: Union[str, Sequence[str], None] = 'f8e17c8d9eaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("budget_commitments", sa.Column("released_amount", sa.Numeric()))
    op.add_column("budget_commitments", sa.Column("released_at", sa.DateTime(timezone=True)))
    op.add_column("budget_commitments", sa.Column("release_reason", sa.Text()))


def downgrade() -> None:
    for col in ("release_reason", "released_at", "released_amount"):
        op.drop_column("budget_commitments", col)
