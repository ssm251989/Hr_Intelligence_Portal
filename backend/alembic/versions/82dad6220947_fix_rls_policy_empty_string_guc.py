"""fix RLS policies: NULLIF empty-string app.tenant_id before casting to uuid

A pooled connection that previously had app.tenant_id set via plain SET (not SET LOCAL)
and was then rolled back reverts the custom GUC to '' (empty string), not NULL -- confirmed
directly against this app's own Postgres. The original policy expression
(`current_setting('app.tenant_id', true)::uuid`) raises casting '' to uuid instead of
failing closed the way an actual NULL does. See app.platform.tenancy.rls's own updated
comment. app.core.database's own SET LOCAL re-applies at the start of every real request's
transaction regardless, so this never affected normal request traffic -- it surfaced
writing test_tenant_isolation.py, exercising a raw pooled connection directly.

Revision ID: 82dad6220947
Revises: 665dae90bd08
Create Date: 2026-09-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '82dad6220947'
down_revision: Union[str, Sequence[str], None] = '665dae90bd08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table enable_rls() has been called for so far.
TABLES = (
    "applications", "audit_log", "bgv_documents", "candidates", "hr_inbound_emails",
    "hr_integrations", "interviews", "interview_confirmation_tokens",
    "interview_scheduling_settings", "job_roles", "local_import_settings",
    "negotiation_tokens", "offers", "screening_settings", "users", "user_integrations",
    "setting_values", "setting_value_history", "secrets", "secret_scopes",
)

_OLD_EXPR = "tenant_id = current_setting('app.tenant_id', true)::uuid"
_NEW_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER POLICY "{table}_tenant_isolation" ON "{table}" USING ({_NEW_EXPR}) WITH CHECK ({_NEW_EXPR})')


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER POLICY "{table}_tenant_isolation" ON "{table}" USING ({_OLD_EXPR}) WITH CHECK ({_OLD_EXPR})')
