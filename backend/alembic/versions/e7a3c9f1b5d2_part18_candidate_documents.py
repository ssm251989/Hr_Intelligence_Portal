"""part18 candidate joining documents

Revision ID: e7a3c9f1b5d2
Revises: d4f8b2e6a1c3
Create Date: 2026-09-28 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'e7a3c9f1b5d2'
down_revision: Union[str, Sequence[str], None] = 'd4f8b2e6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('candidate_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('doc_code', sa.String(length=60), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('file_path', sa.Text(), nullable=False),
    sa.Column('original_name', sa.Text(), nullable=True),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('check_level', sa.String(length=10), nullable=True),
    sa.Column('check_output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hr_status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('hr_note', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.String(length=200), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_candidate_documents_application_id'), 'candidate_documents', ['application_id'], unique=False)
    op.create_index(op.f('ix_candidate_documents_tenant_id'), 'candidate_documents', ['tenant_id'], unique=False)
    enable_rls(op, "candidate_documents")


def downgrade() -> None:
    disable_rls(op, "candidate_documents")
    op.drop_table('candidate_documents')
