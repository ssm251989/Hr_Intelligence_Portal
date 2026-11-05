"""part17 interviewer pools (interviews without Excel)

Revision ID: a6d3f8b2c4e1
Revises: f5c8e1a3d7b9
Create Date: 2026-09-27 17:00:00

Also moves `recruitment.negotiation.busy_source` off "excel" (the tracker is no longer read).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'a6d3f8b2c4e1'
down_revision: Union[str, Sequence[str], None] = 'f5c8e1a3d7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('interviewer_pools',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('job_role_id', sa.UUID(), nullable=True),
    sa.Column('skills_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('member_emails_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('source', sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interviewer_pools_job_role_id'), 'interviewer_pools', ['job_role_id'], unique=False)
    op.create_index(op.f('ix_interviewer_pools_tenant_id'), 'interviewer_pools', ['tenant_id'], unique=False)
    enable_rls(op, "interviewer_pools")
    op.execute("""UPDATE setting_values SET value_json = '"internal"'::jsonb, updated_by = 'migration part17'
                  WHERE key = 'recruitment.negotiation.busy_source' AND value_json = '"excel"'::jsonb""")


def downgrade() -> None:
    disable_rls(op, "interviewer_pools")
    op.drop_table('interviewer_pools')
