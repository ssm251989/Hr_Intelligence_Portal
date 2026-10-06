"""part 21.1: closed jobs -> Recycle bin after N days (job_roles soft delete + pause), applications.removed_reason;
part 21.2 uses removed_reason 'exit' for hiring data moved on exit

Revision ID: b4ad3e4f5a6b
Revises: a39c2d3e4f5a
Create Date: 2026-10-06 22:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b4ad3e4f5a6b'
down_revision: Union[str, Sequence[str], None] = 'a39c2d3e4f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_roles', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('job_roles', sa.Column('deleted_by', sa.Text(), nullable=True))
    op.add_column('job_roles', sa.Column('cleanup_paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('job_roles', sa.Column('cleanup_paused_by', sa.Text(), nullable=True))
    op.create_index('ix_job_roles_deleted_at', 'job_roles', ['deleted_at'])
    op.add_column('applications', sa.Column('removed_reason', sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'removed_reason')
    op.drop_index('ix_job_roles_deleted_at', 'job_roles')
    for c in ('cleanup_paused_by', 'cleanup_paused_at', 'deleted_by', 'deleted_at'):
        op.drop_column('job_roles', c)
