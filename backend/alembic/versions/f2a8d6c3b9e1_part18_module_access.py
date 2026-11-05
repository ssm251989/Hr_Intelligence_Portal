"""part18 module access (unlock passcode)

Revision ID: f2a8d6c3b9e1
Revises: e9c2b5f8a1d4
Create Date: 2026-09-28 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'f2a8d6c3b9e1'
down_revision: Union[str, Sequence[str], None] = 'e9c2b5f8a1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('module_access',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('module_key', sa.String(length=50), nullable=False),
    sa.Column('passcode_hash', sa.Text(), nullable=True),
    sa.Column('unlocked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('unlocked_by', sa.String(length=200), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('lockout_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'module_key', name='module_access_key_uq')
    )
    op.create_index(op.f('ix_module_access_tenant_id'), 'module_access', ['tenant_id'], unique=False)
    enable_rls(op, "module_access")


def downgrade() -> None:
    disable_rls(op, "module_access")
    op.drop_table('module_access')
