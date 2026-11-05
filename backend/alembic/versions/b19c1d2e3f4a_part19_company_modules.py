"""part19 company modules (choose what you use) + screening against a pasted job description

Existing companies keep exactly what they have today: every hiring module active, Onboarding
active only if it is switched on now (setting platform.modules.enabled). New companies start
with nothing and request an activation code.

Revision ID: b19c1d2e3f4a
Revises: a3d5f7b9c1e4
Create Date: 2026-10-03 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.tenancy.rls import disable_rls, enable_rls

revision: str = 'b19c1d2e3f4a'
down_revision: Union[str, Sequence[str], None] = 'a3d5f7b9c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HIRING = ("jobs", "candidates", "screening", "shortlisting", "interviews", "candidate_emails", "salary", "bgv", "offers", "reports")


def _tenant_ids() -> list[str]:
    """Companies come from the control plane: this connection can't see any company's rows
    until app.tenant_id is set (RLS fails closed)."""
    try:
        from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
        from app.platform.tenancy.models_cp import Tenant

        cp_db = ControlPlaneSessionLocal()
        try:
            return [str(t.id) for t in cp_db.query(Tenant).all()]
        finally:
            cp_db.close()
    except Exception:  # no control plane (fresh install) -> nothing to keep
        return []


def upgrade() -> None:
    op.create_table('company_modules',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('module_key', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'off'"), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_by', sa.String(length=200), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_by', sa.String(length=200), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('off','pending','active')", name='company_modules_status_check'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'module_key', name='company_modules_key_uq')
    )
    op.create_index(op.f('ix_company_modules_tenant_id'), 'company_modules', ['tenant_id'], unique=False)
    enable_rls(op, "company_modules")

    op.create_table('jd_screenings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('jd_text', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jd_screenings_tenant_id'), 'jd_screenings', ['tenant_id'], unique=False)
    enable_rls(op, "jd_screenings")

    op.create_table('jd_screening_results',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('screening_id', sa.UUID(), nullable=False),
    sa.Column('candidate_id', sa.UUID(), nullable=False),
    sa.Column('match_score', sa.Integer(), nullable=True),
    sa.Column('recommendation', sa.String(length=30), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['screening_id'], ['jd_screenings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jd_screening_results_tenant_id'), 'jd_screening_results', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_jd_screening_results_screening_id'), 'jd_screening_results', ['screening_id'], unique=False)
    enable_rls(op, "jd_screening_results")

    # existing companies: no change in behaviour
    conn = op.get_bind()
    for tid in _tenant_ids():
        conn.execute(sa.text("select set_config('app.tenant_id', :t, true)"), {"t": tid})
        if not conn.execute(sa.text("select exists(select 1 from users)")).scalar():
            continue  # this company's data lives in another database
        enabled = conn.execute(sa.text("select value_json from setting_values where key = 'platform.modules.enabled' and scope_type = 'tenant'")).scalar()
        keys = list(HIRING) + (["onboarding"] if enabled is None or "onboarding" in (enabled or []) else [])
        for key in keys:
            conn.execute(sa.text(
                "insert into company_modules (id, tenant_id, module_key, status, activated_at, activated_by) "
                "values (gen_random_uuid(), cast(:t as uuid), :k, 'active', now(), 'migration b19c1d2e3f4a') on conflict do nothing"), {"t": tid, "k": key})
    conn.execute(sa.text("select set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    disable_rls(op, "jd_screening_results")
    op.drop_table('jd_screening_results')
    disable_rls(op, "jd_screenings")
    op.drop_table('jd_screenings')
    disable_rls(op, "company_modules")
    op.drop_table('company_modules')
