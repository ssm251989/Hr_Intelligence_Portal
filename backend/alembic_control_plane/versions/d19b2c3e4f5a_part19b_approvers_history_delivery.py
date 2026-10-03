"""part19.2b/c approver priorities, request history, delivery + retries, request numbers

Seeds Priority 1 = kg@ctdtechs.com (owner, 2026-10-03; P2/P3 to be provided).

Revision ID: d19b2c3e4f5a
Revises: c19a2b3d4e5f
Create Date: 2026-10-03 22:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd19b2c3e4f5a'
down_revision: Union[str, Sequence[str], None] = 'c19a2b3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('activation_approvers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('priority')
    )
    op.execute("insert into activation_approvers (priority, name, email, active, updated_by) values (1, 'KG', 'kg@ctdtechs.com', true, 'migration d19b2c3e4f5a')")

    op.create_table('activation_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('sent_to', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('by', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['request_id'], ['activation_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activation_events_request_id'), 'activation_events', ['request_id'], unique=False)

    for name, col in (
        ('number', sa.Column('number', sa.String(length=20), nullable=True)),
        ('code_ref', sa.Column('code_ref', sa.Text(), nullable=True)),
        ('current_priority', sa.Column('current_priority', sa.Integer(), nullable=True)),
        ('delivery', sa.Column('delivery', sa.String(length=20), server_default=sa.text("'sending'"), nullable=False)),
        ('first_sent_at', sa.Column('first_sent_at', sa.DateTime(timezone=True), nullable=True)),
        ('last_sent_at', sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True)),
        ('first_failed_at', sa.Column('first_failed_at', sa.DateTime(timezone=True), nullable=True)),
        ('next_retry_at', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True)),
        ('retry_count', sa.Column('retry_count', sa.Integer(), server_default=sa.text('0'), nullable=False)),
        ('resend_count', sa.Column('resend_count', sa.Integer(), server_default=sa.text('0'), nullable=False)),
        ('resends_today', sa.Column('resends_today', sa.Integer(), server_default=sa.text('0'), nullable=False)),
        ('resend_day', sa.Column('resend_day', sa.Date(), nullable=True)),
        ('last_resend_at', sa.Column('last_resend_at', sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column('activation_requests', col)
    op.execute("create sequence if not exists activation_request_number_seq")
    # existing requests get numbers in order; their delivery state comes from what happened
    op.execute("""
        update activation_requests r set number = 'ACT-' || to_char(r.created_at, 'YYYY') || '-' || lpad(nextval('activation_request_number_seq')::text, 5, '0')
        from (select id from activation_requests order by created_at) o where o.id = r.id
    """)
    op.execute("update activation_requests set delivery = case when emailed_at is not null then 'sent' else 'retrying' end, "
               "first_sent_at = emailed_at, last_sent_at = emailed_at, current_priority = 1, "
               "first_failed_at = case when emailed_at is null then created_at end, next_retry_at = case when emailed_at is null then now() end")
    op.create_unique_constraint('activation_requests_number_uq', 'activation_requests', ['number'])


def downgrade() -> None:
    op.drop_constraint('activation_requests_number_uq', 'activation_requests', type_='unique')
    for name in ('last_resend_at', 'resend_day', 'resends_today', 'resend_count', 'retry_count', 'next_retry_at', 'first_failed_at',
                 'last_sent_at', 'first_sent_at', 'delivery', 'current_priority', 'code_ref', 'number'):
        op.drop_column('activation_requests', name)
    op.execute("drop sequence if exists activation_request_number_seq")
    op.drop_index(op.f('ix_activation_events_request_id'), table_name='activation_events')
    op.drop_table('activation_events')
    op.drop_table('activation_approvers')
