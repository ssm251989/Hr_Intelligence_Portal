"""add tenant_id to every existing table, backfill tenant #1, enable RLS

Part 2 (docs/HRMS_COMPLETE_SPEC.txt) section 3: "MIGRATE EXISTING DATA TO TENANT #1" --
every existing table (all 16 of them, confirmed by grepping every model file's
__tablename__) gets tenant_id UUID NOT NULL, backfilled with the well-known tenant #1 id
(app.platform.tenancy.context.TENANT_1_ID -- a literal here deliberately, so this migration
and hrctl tenant bootstrap-existing agree on the same id without a control-plane round
trip; see that constant's own comment for why this is the one tenant id ever allowed to be
a literal in code), then row-level security enabled (app.platform.tenancy.rls.enable_rls)
so a raw/non-ORM query is covered by tenant isolation too, not just the ORM's own
TenantOwned read filter.

Revision ID: 30cb603c4306
Revises: a7c4f9e1b3d6
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from app.platform.tenancy.rls import disable_rls, enable_rls

# revision identifiers, used by Alembic.
revision: str = '30cb603c4306'
down_revision: Union[str, Sequence[str], None] = 'a7c4f9e1b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every __tablename__ across backend/app/models/*.py as of this migration (Part 1's own
# module parity checklist confirmed this list against the code, not the other way around).
TENANT_TABLES = (
    "applications", "audit_log", "bgv_documents", "candidates", "hr_inbound_emails",
    "hr_integrations", "interviews", "interview_confirmation_tokens",
    "interview_scheduling_settings", "job_roles", "local_import_settings",
    "negotiation_tokens", "offers", "screening_settings", "users", "user_integrations",
)

TENANT_1_ID_LITERAL = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
        op.execute(f'UPDATE "{table}" SET tenant_id = \'{TENANT_1_ID_LITERAL}\' WHERE tenant_id IS NULL')
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        enable_rls(op, table)


def downgrade() -> None:
    for table in TENANT_TABLES:
        disable_rls(op, table)
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
