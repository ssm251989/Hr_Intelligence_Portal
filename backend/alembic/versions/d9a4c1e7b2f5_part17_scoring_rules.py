"""part17 configurable scoring rules + one shortlist threshold

Revision ID: d9a4c1e7b2f5
Revises: c7e2a9d4f1b8
Create Date: 2026-09-27 12:00:00

Additive: two new tables, new nullable/defaulted columns, and a copy of each company's
"interview-ready" mark (recruitment.screening.interview_min_score) into the single
recruitment.scoring.shortlist_threshold setting. The old setting rows are left in place.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'd9a4c1e7b2f5'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9d4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scoring_rule_sets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('job_role_id', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('rules_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'job_role_id', 'version', name='scoring_rule_sets_version_uq')
    )
    op.create_index(op.f('ix_scoring_rule_sets_job_role_id'), 'scoring_rule_sets', ['job_role_id'], unique=False)
    op.create_index(op.f('ix_scoring_rule_sets_tenant_id'), 'scoring_rule_sets', ['tenant_id'], unique=False)
    op.create_table('score_recalc_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('job_role_id', sa.UUID(), nullable=True),
    sa.Column('rule_set_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('total', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('done', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('changed', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_set_id'], ['scoring_rule_sets.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_score_recalc_runs_tenant_id'), 'score_recalc_runs', ['tenant_id'], unique=False)
    for table in ("scoring_rule_sets", "score_recalc_runs"):
        enable_rls(op, table)

    op.add_column('applications', sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('applications', sa.Column('knocked_out', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('applications', sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('scoring_rule_set_id', sa.UUID(), nullable=True))
    op.create_foreign_key('applications_scoring_rule_set_fk', 'applications', 'scoring_rule_sets', ['scoring_rule_set_id'], ['id'], ondelete='SET NULL')
    op.add_column('candidates', sa.Column('current_ctc', sa.Numeric(), nullable=True))
    op.add_column('candidates', sa.Column('expected_ctc', sa.Numeric(), nullable=True))
    op.add_column('candidates', sa.Column('notice_period_days', sa.Integer(), nullable=True))
    op.add_column('candidates', sa.Column('willing_to_relocate', sa.Boolean(), nullable=True))
    op.add_column('candidates', sa.Column('languages', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('job_roles', sa.Column('shortlisting_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))

    # one threshold: carry each company's interview-ready mark over (only where it was set)
    op.execute("""
        INSERT INTO setting_values (id, tenant_id, key, scope_type, scope_id, value_json, version, updated_by, updated_at)
        SELECT gen_random_uuid(), sv.tenant_id, 'recruitment.scoring.shortlist_threshold', sv.scope_type, sv.scope_id,
               sv.value_json, 1, 'migration part17', now()
        FROM setting_values sv
        WHERE sv.key = 'recruitment.screening.interview_min_score'
          AND NOT EXISTS (SELECT 1 FROM setting_values x WHERE x.tenant_id = sv.tenant_id
                          AND x.key = 'recruitment.scoring.shortlist_threshold' AND x.scope_type = sv.scope_type
                          AND x.scope_id IS NOT DISTINCT FROM sv.scope_id)
    """)


def downgrade() -> None:
    op.execute("DELETE FROM setting_values WHERE key = 'recruitment.scoring.shortlist_threshold' AND updated_by = 'migration part17'")
    op.drop_column('job_roles', 'shortlisting_json')
    for col in ('languages', 'willing_to_relocate', 'notice_period_days', 'expected_ctc', 'current_ctc'):
        op.drop_column('candidates', col)
    op.drop_constraint('applications_scoring_rule_set_fk', 'applications', type_='foreignkey')
    for col in ('scoring_rule_set_id', 'scored_at', 'knocked_out', 'score_breakdown'):
        op.drop_column('applications', col)
    for table in ("score_recalc_runs", "scoring_rule_sets"):
        disable_rls(op, table)
    op.drop_table('score_recalc_runs')
    op.drop_table('scoring_rule_sets')
