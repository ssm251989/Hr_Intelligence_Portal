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


def release(db: Session, tenant, application_id, reason: Optional[str] = None) -> None:
    """Candidate dropped out (rejected, withdrew, removed, job closed) -> money back to the budget."""
    row = _row(db, tenant, application_id)
    if row is not None and row.state != "released":
        now = datetime.now(timezone.utc)
        row.state, row.updated_at = "released", now
        row.released_amount, row.released_at = row.amount, now  # Part 21.7: shown in the finance history
        row.release_reason = reason or _dropout_reason(db, application_id)
        db.commit()


def _dropout_reason(db: Session, application_id) -> str:
    from app.models.candidate import Candidate

    app = db.get(Application, application_id)
    cand = db.get(Candidate, app.candidate_id) if app else None
    label = {"offer_withdrawn": "offer withdrawn", "offer_declined": "offer declined", "no_show": "did not join", "bgv_rejected": "BGV failed",
             "rejected": "rejected", "withdrawn": "withdrew", "hr_rejected": "rejected", "interview_rejected": "not selected after the interview",
             "salary_rejected": "salary not agreed", "left_after_joining": "left after joining"}.get(app.status if app else "", "dropped out")
    # (Part 23.3c: an unknown status no longer becomes the reason - "Gunda Kishore - salary approved" was a removal)
    return f"{cand.full_name if cand else 'A candidate'} - {label}"


def _fy_bounds(db: Session, tenant, fy: str) -> tuple[date, date]:
    start_month = int(_setting(db, tenant, "org.fiscal_year_start_month") or 4)
    first = int(str(fy)[:4])
    start = date(first, start_month, 1)
    end = date(first + 1, start_month, 1) if start_month != 1 else date(first + 1, 1, 1)
    return start, end


def release_on_exit(db: Session, tenant, separation, *, actor: str) -> Optional[dict]:
    """Part 21.7: a person exits -> their committed salary goes back to the department budget.
    Pro-rata (default): only the months of the budget year after their last working day; or the full annual amount."""
    from app.audit.service import log_action
    from app.employees import directory
    from app.models.core_hr import Employee
    from app.models.onboarding import PreboardingCase

    if _setting(db, tenant, "recruitment.budgets.release_on_exit") is False:
        return None
    case = (db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.employee_id == separation.employee_id,
                                             PreboardingCase.application_id.isnot(None)).order_by(PreboardingCase.created_at.desc()).first())
    row = _row(db, tenant, case.application_id) if case else None
    if row is None or row.state == "released":
        return None
    lwd = separation.approved_lwd or date.today()
    start, end = _fy_bounds(db, tenant, row.fiscal_year)
    amount = float(row.amount)
    mode = _setting(db, tenant, "recruitment.budgets.release_mode") or "pro_rata"
    if mode == "full" or lwd < start:
        released = amount
    elif lwd >= end:
        released = 0.0
    else:
        months_left = (end.year - lwd.year) * 12 + (end.month - lwd.month) - 1  # whole months after the LWD's month
        released = round(amount * max(0, months_left) / 12, 2)
    if released <= 0:
        return {"released": 0, "reason": "the budget year is over"}
    e = db.get(Employee, separation.employee_id)
    name = directory.name_of(e) if e else "An employee"
    now = datetime.now(timezone.utc)
    row.released_amount = released
    row.released_at = now
    row.release_reason = f"{name} exited ({row.job_title or 'role'}) on {lwd.strftime('%d %b %Y')}"
    if released >= amount:
        row.state = "released"
    else:
        row.amount = round(amount - released, 2)  # the part already spent stays committed
    row.updated_at = now
    db.commit()
    log_action(db, "budget", row.id, "budget_released_on_exit", actor[:50],
               {"department": row.department, "fiscal_year": row.fiscal_year, "released": released, "mode": mode, "employee": name,
                "last_working_day": lwd.isoformat(), "annual_amount": amount})
    return {"released": released, "mode": mode, "department": row.department}


def history(db: Session, tenant, fy: str, limit: int = 50) -> list[dict]:
    """Part 21.7: money that came back to the budgets this year, newest first."""
    rows = (db.query(BudgetCommitment).filter(BudgetCommitment.tenant_id == tenant.tenant_id, BudgetCommitment.fiscal_year == fy,
                                              BudgetCommitment.released_at.isnot(None)).order_by(BudgetCommitment.released_at.desc()).limit(limit).all())
    return [{"department": r.department, "job_title": r.job_title, "amount": float(r.released_amount or 0), "on": r.released_at.isoformat(),
             "reason": r.release_reason} for r in rows]
