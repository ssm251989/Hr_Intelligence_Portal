"""part18 department budgets + commitments

Revision ID: d4f8b2e6a1c3
Revises: c9e4a2d8f6b1
Create Date: 2026-09-28 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'd4f8b2e6a1c3'
down_revision: Union[str, Sequence[str], None] = 'c9e4a2d8f6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('department_budgets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('department', sa.Text(), nullable=False),
    sa.Column('fiscal_year', sa.String(length=9), nullable=False),
    sa.Column('allocated', sa.Numeric(), nullable=False),
    sa.Column('quarters_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('alert_pct', sa.Integer(), server_default=sa.text('80'), nullable=False),
    sa.Column('on_exceed', sa.String(length=20), server_default=sa.text("'needs_approval'"), nullable=False),
    sa.Column('updated_by', sa.String(length=200), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'department', 'fiscal_year', name='department_budgets_dept_fy_uq'))
    op.create_index(op.f('ix_department_budgets_tenant_id'), 'department_budgets', ['tenant_id'], unique=False)
    enable_rls(op, "department_budgets")
    op.create_table('budget_commitments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('department', sa.Text(), nullable=False),
    sa.Column('fiscal_year', sa.String(length=9), nullable=False),
    sa.Column('job_title', sa.Text(), nullable=True),
    sa.Column('amount', sa.Numeric(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'application_id', name='budget_commitments_application_uq'))
    op.create_index(op.f('ix_budget_commitments_tenant_id'), 'budget_commitments', ['tenant_id'], unique=False)
    enable_rls(op, "budget_commitments")


def downgrade() -> None:
    disable_rls(op, "budget_commitments")
    op.drop_table('budget_commitments')
    disable_rls(op, "department_budgets")
    op.drop_table('department_budgets')
