"""Part 18.13/18.15: department hiring budgets and the money each hire takes from them.

DepartmentBudget: per department and financial year ("2026-27"): allocated amount, optional
per-quarter split, alert threshold %, what happens when exceeded (needs_approval | block).
BudgetCommitment: one row per application -- "reserved" when its salary is approved,
"committed" when the offer is accepted, "released" if the candidate drops out.
Amounts are yearly CTC in the company currency. TenantOwned + RLS."""

import uuid

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class DepartmentBudget(Base, TenantOwned):
    __tablename__ = "department_budgets"
    __table_args__ = (UniqueConstraint("tenant_id", "department", "fiscal_year", name="department_budgets_dept_fy_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department = Column(Text, nullable=False)
    fiscal_year = Column(String(9), nullable=False)  # "2026-27"
    allocated = Column(Numeric, nullable=False)
    quarters_json = Column(JSONB)  # optional {"Q1": n, "Q2": n, "Q3": n, "Q4": n}
    alert_pct = Column(Integer, nullable=False, server_default=text("80"))
    on_exceed = Column(String(20), nullable=False, server_default=text("'needs_approval'"))  # needs_approval | block
    updated_by = Column(String(200))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class BudgetCommitment(Base, TenantOwned):
    __tablename__ = "budget_commitments"
    __table_args__ = (UniqueConstraint("tenant_id", "application_id", name="budget_commitments_application_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), nullable=False)  # not a FK: the row outlives a deleted application as released history
    department = Column(Text, nullable=False)
    fiscal_year = Column(String(9), nullable=False)
    job_title = Column(Text)
    amount = Column(Numeric, nullable=False)
    state = Column(String(20), nullable=False)  # reserved | committed | released
    # Part 21.7: what went back to the department budget, when and why (finance dashboard history)
    released_amount = Column(Numeric)
    released_at = Column(DateTime(timezone=True))
    release_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
