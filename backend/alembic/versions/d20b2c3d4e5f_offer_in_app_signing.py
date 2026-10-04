"""offers: in-app signing (link, viewed / signed times, typed name, IP, stamped PDF)

Revision ID: d20b2c3d4e5f
Revises: c20a1b2c3d4e
Create Date: 2026-10-04 17:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd20b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = 'c20a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLS = (("sign_token", sa.Text()), ("sent_at", sa.DateTime(timezone=True)), ("viewed_at", sa.DateTime(timezone=True)),
        ("signed_at", sa.DateTime(timezone=True)), ("signed_name", sa.Text()), ("signed_ip", sa.String(length=64)),
        ("signed_user_agent", sa.Text()), ("signed_pdf_path", sa.Text()), ("sign_method", sa.String(length=20)))


def upgrade() -> None:
    for name, typ in COLS:
        op.add_column('offers', sa.Column(name, typ, nullable=True))
    op.create_unique_constraint('offers_sign_token_uq', 'offers', ['sign_token'])


def downgrade() -> None:
    op.drop_constraint('offers_sign_token_uq', 'offers', type_='unique')
    for name, _typ in reversed(COLS):
        op.drop_column('offers', name)
