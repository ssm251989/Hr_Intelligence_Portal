"""part15 agency portal

Revision ID: b3d8f2a61c47
Revises: e78fd7f330b5
Create Date: 2026-09-26 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.platform.tenancy.rls import disable_rls, enable_rls


revision: str = 'b3d8f2a61c47'
down_revision: Union[str, Sequence[str], None] = 'e78fd7f330b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("recruitment_agencies", "agency_members", "agency_job_assignments", "agency_submissions")
OLD_SOURCES = ("career_portal", "manual", "local_import", "linkedin", "naukri", "indeed", "monster", "shine")


def _sources(values) -> str:
    return "source IN (" + ",".join(f"'{s}'" for s in values) + ")"


def upgrade() -> None:
    op.create_table('recruitment_agencies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name', name='recruitment_agencies_name_uq')
    )
    op.create_index(op.f('ix_recruitment_agencies_tenant_id'), 'recruitment_agencies', ['tenant_id'], unique=False)
    op.create_table('agency_members',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agency_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['agency_id'], ['recruitment_agencies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'user_id', name='agency_members_user_uq')
    )
    op.create_index(op.f('ix_agency_members_agency_id'), 'agency_members', ['agency_id'], unique=False)
    op.create_index(op.f('ix_agency_members_tenant_id'), 'agency_members', ['tenant_id'], unique=False)
    op.create_table('agency_job_assignments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agency_id', sa.UUID(), nullable=False),
    sa.Column('job_role_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['agency_id'], ['recruitment_agencies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'agency_id', 'job_role_id', name='agency_job_assignments_uq')
    )
    op.create_index(op.f('ix_agency_job_assignments_agency_id'), 'agency_job_assignments', ['agency_id'], unique=False)
    op.create_index(op.f('ix_agency_job_assignments_tenant_id'), 'agency_job_assignments', ['tenant_id'], unique=False)
    op.create_table('agency_submissions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agency_id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('submitted_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['agency_id'], ['recruitment_agencies.id'], ),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'application_id', name='agency_submissions_application_uq')
    )
    op.create_index(op.f('ix_agency_submissions_agency_id'), 'agency_submissions', ['agency_id'], unique=False)
    op.create_index(op.f('ix_agency_submissions_tenant_id'), 'agency_submissions', ['tenant_id'], unique=False)
    for table in TABLES:
        enable_rls(op, table)

    op.drop_constraint("users_role_check", "users", type_="check")
    op.create_check_constraint("users_role_check", "users", "role IN ('recruiter','hiring_manager','interviewer','admin','employee','agency')")
    op.drop_constraint("candidates_source_check", "candidates", type_="check")
    op.create_check_constraint("candidates_source_check", "candidates", _sources(OLD_SOURCES + ("agency",)))


def downgrade() -> None:
    # Fails loudly (rather than deleting rows) if agency users / agency candidates exist.
    op.drop_constraint("candidates_source_check", "candidates", type_="check")
    op.create_check_constraint("candidates_source_check", "candidates", _sources(OLD_SOURCES))
    op.drop_constraint("users_role_check", "users", type_="check")
    op.create_check_constraint("users_role_check", "users", "role IN ('recruiter','hiring_manager','interviewer','admin','employee')")
    for table in TABLES:
        disable_rls(op, table)
    for table in reversed(TABLES):
        op.drop_table(table)
