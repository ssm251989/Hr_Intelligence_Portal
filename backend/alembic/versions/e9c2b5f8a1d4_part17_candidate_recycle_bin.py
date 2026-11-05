"""part17 candidate recycle bin

Revision ID: e9c2b5f8a1d4
Revises: c3f7a1d9e5b2
Create Date: 2026-09-27 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'e9c2b5f8a1d4'
down_revision: Union[str, Sequence[str], None] = 'c3f7a1d9e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('candidates', sa.Column('deleted_by', sa.String(length=200), nullable=True))
    op.add_column('candidates', sa.Column('delete_reason', sa.String(length=30), nullable=True))
    op.add_column('candidates', sa.Column('delete_note', sa.Text(), nullable=True))
    op.create_index(op.f('ix_candidates_deleted_at'), 'candidates', ['deleted_at'], unique=False)
    op.add_column('applications', sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('candidate_removal_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('candidate_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('done', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('skipped', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'running'"), nullable=False),
    sa.Column('started_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_candidate_removal_runs_tenant_id'), 'candidate_removal_runs', ['tenant_id'], unique=False)
    enable_rls(op, "candidate_removal_runs")


def downgrade() -> None:
    disable_rls(op, "candidate_removal_runs")
    op.drop_table('candidate_removal_runs')
    op.drop_column('applications', 'removed_at')
    op.drop_index(op.f('ix_candidates_deleted_at'), table_name='candidates')
    for c in ('delete_note', 'delete_reason', 'deleted_by', 'deleted_at'):
        op.drop_column('candidates', c)
