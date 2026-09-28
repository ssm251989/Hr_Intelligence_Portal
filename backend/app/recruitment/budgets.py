"""Part 18.13/18.15: department hiring budgets.

Example: department budget 50 L, a hire approved at 10 L -> 10 L "reserved", 40 L remaining;
the offer is accepted -> "committed"; the candidate drops out -> "released" (money back).
The financial year starts in the month of setting org.fiscal_year_start_month (India: April).
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.department_budget import BudgetCommitment, DepartmentBudget
from app.models.job_role import JobRole


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def fiscal_year(db: Session, tenant, when: Optional[date] = None) -> str:
    when = when or date.today()
    start = int(_setting(db, tenant, "org.fiscal_year_start_month") or 4)
    first = when.year if when.month >= start else when.year - 1
    return f"{first}-{str(first + 1)[-2:]}" if start != 1 else str(first)


def budget_for(db: Session, tenant, department: Optional[str], fy: Optional[str] = None) -> Optional[DepartmentBudget]:
    if not department:
        return None
    return db.query(DepartmentBudget).filter(DepartmentBudget.tenant_id == tenant.tenant_id, DepartmentBudget.department == department,
                                             DepartmentBudget.fiscal_year == (fy or fiscal_year(db, tenant))).first()


def usage(db: Session, tenant, department: str, fy: str, *, exclude_application=None) -> dict:
    q = db.query(BudgetCommitment.state, func.coalesce(func.sum(BudgetCommitment.amount), 0)).filter(
        BudgetCommitment.tenant_id == tenant.tenant_id, BudgetCommitment.department == department, BudgetCommitment.fiscal_year == fy,
        BudgetCommitment.state.in_(("reserved", "committed")))
    if exclude_application is not None:
        q = q.filter(BudgetCommitment.application_id != exclude_application)
    by = {s: float(v) for s, v in q.group_by(BudgetCommitment.state)}
    return {"reserved": by.get("reserved", 0.0), "committed": by.get("committed", 0.0)}


def check(db: Session, tenant, application: Application, job: JobRole, amount: Optional[float]) -> dict:
    """-> {"configured", "department", "fiscal_year", "allocated", "used", "remaining", "short_by", "ok", "on_exceed"}"""
    fy = fiscal_year(db, tenant)
    b = budget_for(db, tenant, job.department, fy)
    if b is None:
        return {"configured": False, "department": job.department, "fiscal_year": fy, "ok": True}
    u = usage(db, tenant, b.department, fy, exclude_application=application.id)
    used = u["reserved"] + u["committed"]
    remaining = float(b.allocated) - used
    need = float(amount or 0)
    short = max(0.0, need - remaining)
    return {"configured": True, "department": b.department, "fiscal_year": fy, "allocated": float(b.allocated), "used": used,
            "remaining": remaining, "after_hire": remaining - need, "short_by": short, "ok": short == 0, "on_exceed": b.on_exceed,
            "alert_pct": b.alert_pct}


def _row(db, tenant, application_id) -> Optional[BudgetCommitment]:
    return db.query(BudgetCommitment).filter(BudgetCommitment.tenant_id == tenant.tenant_id, BudgetCommitment.application_id == application_id).first()


def reserve(db: Session, tenant, application: Application, job: JobRole, amount: Optional[float]) -> Optional[BudgetCommitment]:
    """Salary approved -> the amount is reserved against the department's budget (if it has one)."""
    if amount is None or not job.department:
        return None
    fy = fiscal_year(db, tenant)
    row = _row(db, tenant, application.id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = BudgetCommitment(tenant_id=tenant.tenant_id, application_id=application.id, department=job.department, fiscal_year=fy,
                               job_title=job.title, amount=amount, state="reserved")
        db.add(row)
    else:
        row.amount, row.state, row.department, row.fiscal_year, row.updated_at = amount, "reserved" if row.state != "committed" else "committed", job.department, fy, now
    db.commit()
    return row


def commit(db: Session, tenant, application_id) -> None:
    """Offer accepted / signed -> committed."""
    row = _row(db, tenant, application_id)
    if row is not None and row.state != "committed":
        row.state, row.updated_at = "committed", datetime.now(timezone.utc)
        db.commit()


def release(db: Session, tenant, application_id) -> None:
    """Candidate dropped out (rejected, withdrew, removed, job closed) -> money back to the budget."""
    row = _row(db, tenant, application_id)
    if row is not None and row.state != "released":
        row.state, row.updated_at = "released", datetime.now(timezone.utc)
        db.commit()
