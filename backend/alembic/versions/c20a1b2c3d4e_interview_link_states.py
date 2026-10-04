"""interview links: why a link stopped working, when it was opened, retired links

Revision ID: c20a1b2c3d4e
Revises: b19c1d2e3f4a
Create Date: 2026-10-04 16:45:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c20a1b2c3d4e'
down_revision: Union[str, Sequence[str], None] = 'b19c1d2e3f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('negotiation_tokens', sa.Column('invalidated_reason', sa.Text(), nullable=True))
    op.add_column('negotiation_tokens', sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('retired_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'token_hash', name='retired_links_hash_uq')
    )
    op.create_index(op.f('ix_retired_links_tenant_id'), 'retired_links', ['tenant_id'], unique=False)
    enable_rls(op, "retired_links")


def downgrade() -> None:
    disable_rls(op, "retired_links")
    op.drop_table('retired_links')
    op.drop_column('negotiation_tokens', 'opened_at')
    op.drop_column('negotiation_tokens', 'invalidated_reason')
