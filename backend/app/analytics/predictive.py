"""Predictive estimates (docs/HRMS_COMPLETE_SPEC.txt Part 12 section A.5) -- clearly
labelled `"kind": "estimate"`, explainable (every score lists its factors), gated by the
`analytics.predictive` AI feature toggle, and human-in-the-loop: an attrition estimate is
written to the talent profile's AI field only; the manager's own assessment always wins
(Part 10 `talent.effective_flight_risk`).

Deliberately transparent heuristics, not a trained model: this installation has no
labelled history to train on, and an unexplainable score would fail the bias review the
AI decision log exists for.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core_hr import lifecycle
from app.core_hr.context import hire_date
from app.models.application import Application
from app.models.core_hr import Employee, EmploymentRecord, Position
from app.models.performance import CompensationRecord, Review, TalentProfile
from app.models.requisition import JobRequisition
from app.platform.ai.governance import AIDisabledError, feature_enabled
from app.platform.tenancy.context import TenantContext

LABEL = {"kind": "estimate", "disclaimer": "Estimate from simple, listed factors -- review before acting."}


def _require_enabled(db: Session, tenant: TenantContext) -> None:
    if not feature_enabled(db, tenant, "analytics.predictive"):
        raise AIDisabledError("predictive analytics is turned off for this organisation")


def attrition_risk(db: Session, tenant: TenantContext, employee: Employee, *, as_of: Optional[date] = None) -> dict:
    """Additive factor score, capped at 1.0."""
    _require_enabled(db, tenant)
    as_of = as_of or datetime.now(timezone.utc).date()
    factors: dict[str, float] = {}
    doj = hire_date(db, tenant, employee)
    if doj and (as_of - doj).days < 365:
        factors["tenure_under_1_year"] = 0.2
    last_change = db.query(func.max(EmploymentRecord.effective_from)).filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id == employee.id).scalar()
    if last_change and (as_of - last_change).days > 730:
        factors["no_role_change_2_years"] = 0.2
    last_comp = db.query(func.max(CompensationRecord.effective_from)).filter(CompensationRecord.tenant_id == tenant.tenant_id, CompensationRecord.employee_id == employee.id).scalar()
    if last_comp is None or (as_of - last_comp).days > 540:
        factors["no_pay_change_18_months"] = 0.2
    latest_rating = (
        db.query(Review.overall_rating).filter(Review.tenant_id == tenant.tenant_id, Review.employee_id == employee.id, Review.status == "submitted", Review.stage == "manager")
        .order_by(Review.submitted_at.desc()).first()
    )
    if latest_rating and latest_rating[0] is not None and float(latest_rating[0]) <= 2:
        factors["low_recent_rating"] = 0.15
    current = lifecycle.get_current_employment(db, tenant, employee.id, as_of=as_of)
    if current and current.manager_employee_id:
        manager_change = db.query(func.count(func.distinct(EmploymentRecord.manager_employee_id))).filter(
            EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id == employee.id,
            EmploymentRecord.effective_from >= as_of - timedelta(days=365)).scalar() or 0
        if manager_change > 1:
            factors["manager_changed_last_year"] = 0.15
    score = round(min(1.0, sum(factors.values())), 2)
    return {**LABEL, "employee_id": str(employee.id), "score": score, "factors": factors}


def refresh_attrition_estimates(db: Session, tenant: TenantContext, employee_ids: Optional[list[UUID]] = None) -> int:
    """Writes the estimate to talent_profiles.flight_risk_ai (never the manager field)."""
    from app.performance import talent

    _require_enabled(db, tenant)
    query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice")))
    if employee_ids:
        query = query.filter(Employee.id.in_(employee_ids))
    count = 0
    for employee in query.all():
        estimate = attrition_risk(db, tenant, employee)
        talent.record_ai_flight_risk(db, talent.get_or_create_profile(db, tenant, employee.id), score=estimate["score"], factors=estimate["factors"])
        count += 1
    return count


def time_to_fill_forecast(db: Session, tenant: TenantContext) -> dict:
    """Mean historical days-to-hire per department, applied to each open requisition."""
    _require_enabled(db, tenant)
    from app.models.job_role import JobRole

    rows = db.query(JobRole.department, Application.created_at, Application.updated_at).join(JobRole, JobRole.id == Application.job_role_id).filter(
        Application.tenant_id == tenant.tenant_id, Application.status == "hired").all()
    by_dept: dict = {}
    for dept, created, updated in rows:
        if created and updated:
            by_dept.setdefault(dept or "unassigned", []).append((updated - created).days)
    overall = [d for v in by_dept.values() for d in v]
    fallback = round(sum(overall) / len(overall), 1) if overall else None
    means = {k: round(sum(v) / len(v), 1) for k, v in by_dept.items()}
    open_reqs = db.query(JobRequisition).filter(JobRequisition.tenant_id == tenant.tenant_id, JobRequisition.status.in_(("approved", "open"))).all()
    return {**LABEL, "department_means_days": means, "overall_mean_days": fallback,
            "open_requisitions": [{"id": str(r.id), "title": r.title, "forecast_days": fallback} for r in open_reqs]}


def headcount_plan_vs_actual(db: Session, tenant: TenantContext) -> dict:
    """Plan = positions' headcount_budget per department; actual = active employees whose
    current record sits in that department."""
    _require_enabled(db, tenant)
    today = datetime.now(timezone.utc).date()
    plan = dict(db.query(Position.department_id, func.coalesce(func.sum(Position.headcount_budget), 0)).filter(Position.tenant_id == tenant.tenant_id).group_by(Position.department_id).all())
    actual_rows = (
        db.query(EmploymentRecord.department_id, func.count(EmploymentRecord.employee_id))
        .join(Employee, Employee.id == EmploymentRecord.employee_id)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice")), EmploymentRecord.effective_from <= today)
        .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= today))
        .group_by(EmploymentRecord.department_id).all()
    )
    actual = dict(actual_rows)
    departments = set(plan) | set(actual)
    return {**LABEL, "departments": [
        {"department_id": str(d) if d else None, "plan": int(plan.get(d, 0)), "actual": int(actual.get(d, 0)), "gap": int(plan.get(d, 0)) - int(actual.get(d, 0))}
        for d in departments
    ]}
