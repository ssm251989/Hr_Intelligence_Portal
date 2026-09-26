"""part17 geo cache

Revision ID: c7e2a9d4f1b8
Revises: b3d8f2a61c47
Create Date: 2026-09-27 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c7e2a9d4f1b8'
down_revision: Union[str, Sequence[str], None] = 'b3d8f2a61c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('geo_cache',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('query_key', sa.String(length=255), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('country_code', sa.String(length=2), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'query_key', name='geo_cache_query_uq')
    )
    op.create_index(op.f('ix_geo_cache_tenant_id'), 'geo_cache', ['tenant_id'], unique=False)
    enable_rls(op, "geo_cache")


def downgrade() -> None:
    disable_rls(op, "geo_cache")
    op.drop_table('geo_cache')
