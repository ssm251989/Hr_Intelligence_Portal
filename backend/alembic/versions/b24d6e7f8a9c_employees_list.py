"""part 20.1 employees list: company email, joined on, previous experience, rehire flag, exit date, candidate link;
employee statuses exited + absconded; users.password_set_at (app account Invited vs Active)

Revision ID: b24d6e7f8a9c
Revises: a23c5d6e7f8b
Create Date: 2026-10-06 10:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'b24d6e7f8a9c'
down_revision: Union[str, Sequence[str], None] = 'a23c5d6e7f8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = ("pre_hire", "active", "on_notice", "inactive", "terminated", "rehire_eligible")
NEW = OLD + ("exited", "absconded")
COLUMNS = (("company_email", sa.Text()), ("company_email_provider", sa.String(20)), ("joined_on", sa.Date()),
           ("previous_experience_months", sa.Integer()), ("rehire_eligible", sa.Boolean()), ("exited_on", sa.Date()),
           ("candidate_id", UUID(as_uuid=True)))


def _in(values) -> str:
    return "status IN (" + ",".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column('employees', sa.Column(name, type_, nullable=True))
    op.create_index('employees_company_email_idx', 'employees', ['tenant_id', 'company_email'])
    op.drop_constraint('employees_status_check', 'employees', type_='check')
    op.create_check_constraint('employees_status_check', 'employees', _in(NEW))
    op.add_column('users', sa.Column('password_set_at', sa.DateTime(timezone=True), nullable=True))
    # everyone who already has an account has (as far as we know) set a password
    op.execute("UPDATE users SET password_set_at = password_changed_at")
    # joined_on from the hire record; previous experience from the resume of the linked candidate
    op.execute("""UPDATE employees e SET joined_on = r.effective_from FROM employment_records r
                  WHERE r.employee_id = e.id AND r.event_type = 'hire' AND e.joined_on IS NULL""")
    op.execute("""UPDATE employees e SET candidate_id = c.candidate_id FROM preboarding_cases c
                  WHERE c.employee_id = e.id AND c.candidate_id IS NOT NULL AND e.candidate_id IS NULL""")


def downgrade() -> None:
    op.drop_column('users', 'password_set_at')
    op.execute("UPDATE employees SET status = 'terminated' WHERE status IN ('exited', 'absconded')")
    op.drop_constraint('employees_status_check', 'employees', type_='check')
    op.create_check_constraint('employees_status_check', 'employees', _in(OLD))
    op.drop_index('employees_company_email_idx', 'employees')
    for name, _ in reversed(COLUMNS):
        op.drop_column('employees', name)
