"""part 20.2b TEST (dummy) email provider: test_mailboxes + test_mailbox_messages (RLS like every tenant table)

Revision ID: c25e7f8a9b0d
Revises: b24d6e7f8a9c
Create Date: 2026-10-06 13:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'c25e7f8a9b0d'
down_revision: Union[str, Sequence[str], None] = 'b24d6e7f8a9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'test_mailboxes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text()),
        sa.Column('employee_id', UUID(as_uuid=True)),
        sa.Column('employee_code', sa.String(50)),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column('quota', sa.String(40), nullable=False, server_default=sa.text("'15 GB (dummy)'")),
        sa.Column('provider', sa.String(20), nullable=False, server_default=sa.text("'TEST'")),
        sa.Column('created_by', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','suspended','deleted')", name='test_mailboxes_status_check'),
        sa.UniqueConstraint('tenant_id', 'address', name='test_mailboxes_tenant_address_uq'),
    )
    op.create_table(
        'test_mailbox_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('mailbox_id', UUID(as_uuid=True), sa.ForeignKey('test_mailboxes.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('to_address', sa.Text(), nullable=False),
        sa.Column('from_address', sa.Text()),
        sa.Column('subject', sa.Text()),
        sa.Column('body_text', sa.Text()),
        sa.Column('body_html', sa.Text()),
        sa.Column('template_key', sa.String(120)),
        sa.Column('outbound_message_id', UUID(as_uuid=True)),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    for t in ('test_mailboxes', 'test_mailbox_messages'):
        enable_rls(op, t)


def downgrade() -> None:
    for t in ('test_mailbox_messages', 'test_mailboxes'):
        disable_rls(op, t)
    op.drop_table('test_mailbox_messages')
    op.drop_table('test_mailboxes')
