"""offer versions (resend / revised offer) + candidate first / last / preferred name

Revision ID: e21a3b4c5d6f
Revises: d20b2c3d4e5f
Create Date: 2026-10-05 13:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'e21a3b4c5d6f'
down_revision: Union[str, Sequence[str], None] = 'd20b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for col in ('first_name', 'last_name', 'preferred_name'):
        op.add_column('candidates', sa.Column(col, sa.String(length=120), nullable=True))
    op.add_column('offers', sa.Column('version_no', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.add_column('offers', sa.Column('designation', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('work_location', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('terms', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('resend_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('offers', sa.Column('last_resent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('offers', sa.Column('declined_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('offer_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('offer_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'current'"), nullable=False),
    sa.Column('letter_html', sa.Text(), nullable=True),
    sa.Column('ctc_total', sa.Numeric(), nullable=True),
    sa.Column('ctc_breakup_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('joining_date', sa.Date(), nullable=True),
    sa.Column('designation', sa.Text(), nullable=True),
    sa.Column('work_location', sa.Text(), nullable=True),
    sa.Column('terms', sa.Text(), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('reason_code', sa.String(length=30), nullable=True),
    sa.Column('reason_note', sa.Text(), nullable=True),
    sa.Column('changes_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('approval_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sent_by', sa.String(length=200), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resend_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('sign_token', sa.Text(), nullable=True),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_name', sa.Text(), nullable=True),
    sa.Column('signed_ip', sa.String(length=64), nullable=True),
    sa.Column('sign_method', sa.String(length=20), nullable=True),
    sa.Column('signed_pdf_path', sa.Text(), nullable=True),
    sa.Column('docusign_envelope_id', sa.String(length=255), nullable=True),
    sa.Column('replaced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('offer_id', 'version_no', name='offer_versions_no_uq'),
    sa.UniqueConstraint('sign_token'),
    )
    op.create_index(op.f('ix_offer_versions_offer_id'), 'offer_versions', ['offer_id'], unique=False)
    op.create_index(op.f('ix_offer_versions_tenant_id'), 'offer_versions', ['tenant_id'], unique=False)
    enable_rls(op, "offer_versions")


def downgrade() -> None:
    disable_rls(op, "offer_versions")
    op.drop_table('offer_versions')
    for col in ('declined_at', 'last_resent_at', 'resend_count', 'terms', 'work_location', 'designation', 'version_no'):
        op.drop_column('offers', col)
    for col in ('preferred_name', 'last_name', 'first_name'):
        op.drop_column('candidates', col)
