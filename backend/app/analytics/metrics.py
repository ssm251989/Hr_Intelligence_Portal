"""HR metrics (docs/HRMS_COMPLETE_SPEC.txt Part 12 section A.4). Every metric takes the
caller's employee scope (`None` = all) so a manager's dashboard only counts their people.
A metric that needs data this installation doesn't hold returns `{"value": None, "reason"}`
rather than a made-up number (cost-per-hire needs a recruiting-spend figure)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.core_hr import Employee, EmploymentRecord
from app.models.offer import Offer
from app.models.onboarding import BgvCase, PreboardingCase
from app.models.performance import Goal
from app.models.service_desk import Asset, Separation, Ticket
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

METRICS = (
    "headcount", "movement", "attrition", "tenure", "span_of_control", "diversity", "time_to_hire", "cost_per_hire",
    "offer_acceptance", "bgv_turnaround", "onboarding_readiness", "ticket_sla", "asset_allocation", "goal_completion",
)


def _scoped(query, column, scope: Optional[set[UUID]]):
    if scope is None:
        return query
    return query.filter(column.in_(list(scope))) if scope else query.filter(False)


def _current(db: Session, tenant: TenantContext, as_of: date):
    return db.query(EmploymentRecord).filter(
        EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_from <= as_of,
        or_(EmploymentRecord.effective_to.is_(None), EmploymentRecord.effective_to >= as_of),
    )


def headcount(db, tenant, scope, as_of: date) -> dict:
    q = _scoped(db.query(func.count(Employee.id)).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice"))), Employee.id, scope)
    return {"value": q.scalar() or 0}


def movement(db, tenant, scope, as_of: date, days: int = 30) -> dict:
    start = as_of - timedelta(days=days)
    hires = _scoped(db.query(func.count(func.distinct(EmploymentRecord.employee_id))).filter(
        EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_from.between(start, as_of),
        ~EmploymentRecord.employee_id.in_(db.query(EmploymentRecord.employee_id).filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_from < start)),
    ), EmploymentRecord.employee_id, scope).scalar() or 0
    exits = _scoped(db.query(func.count(Separation.id)).filter(Separation.tenant_id == tenant.tenant_id, Separation.status == "completed",
                                                               Separation.approved_lwd.between(start, as_of)), Separation.employee_id, scope).scalar() or 0
    return {"value": hires - exits, "hires": hires, "exits": exits, "window_days": days}


def attrition(db, tenant, scope, as_of: date) -> dict:
    start = as_of - timedelta(days=365)
    rows = _scoped(db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status == "completed",
                                               Separation.approved_lwd.between(start, as_of)), Separation.employee_id, scope).all()
    hc = headcount(db, tenant, scope, as_of)["value"]
    base = hc + len(rows) / 2 or 1  # average of start/end headcount approximated from end + half the leavers
    voluntary = sum(1 for r in rows if r.voluntary)
    regretted = sum(1 for r in rows if r.regretted)
    return {"value": round(100 * len(rows) / base, 2), "exits_12m": len(rows), "voluntary_pct": round(100 * voluntary / len(rows), 1) if rows else 0,
            "regretted_pct": round(100 * regretted / len(rows), 1) if rows else 0, "unit": "%"}


def tenure(db, tenant, scope, as_of: date) -> dict:
    first = db.query(EmploymentRecord.employee_id, func.min(EmploymentRecord.effective_from).label("doj")).filter(
        EmploymentRecord.tenant_id == tenant.tenant_id).group_by(EmploymentRecord.employee_id).subquery()
    q = db.query(first.c.doj).join(Employee, Employee.id == first.c.employee_id).filter(Employee.status.in_(("active", "on_notice")))
    q = _scoped(q, Employee.id, scope)
    days = [(as_of - d).days for (d,) in q.all() if d and d <= as_of]
    return {"value": round(sum(days) / len(days) / 365.25, 2) if days else None, "unit": "years"}


def span_of_control(db, tenant, scope, as_of: date) -> dict:
    q = _current(db, tenant, as_of).filter(EmploymentRecord.manager_employee_id.isnot(None))
    q = _scoped(q, EmploymentRecord.employee_id, scope)
    counts: dict = {}
    for r in q.all():
        counts[r.manager_employee_id] = counts.get(r.manager_employee_id, 0) + 1
    return {"value": round(sum(counts.values()) / len(counts), 2) if counts else None, "managers": len(counts)}


def diversity(db, tenant, scope, as_of: date) -> dict:
    """Opt-in (`analytics.diversity.enabled`) and aggregate-only; groups under the tenant's
    minimum group size are folded into "other" so no small group is identifiable."""
    settings = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    if not settings.get("analytics.diversity.enabled", ctx):
        return {"value": None, "reason": "diversity reporting is not enabled for this organisation"}
    min_group = int(settings.get("analytics.diversity.min_group_size", ctx))
    q = _scoped(db.query(Employee.gender, func.count(Employee.id)).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice"))), Employee.id, scope)
    raw = {g or "undisclosed": n for g, n in q.group_by(Employee.gender).all()}
    folded: dict = {}
    for group, n in raw.items():
        key = group if n >= min_group else "other"
        folded[key] = folded.get(key, 0) + n
    total = sum(folded.values())
    return {"value": {k: round(100 * v / total, 1) for k, v in folded.items()} if total else {}, "unit": "%"}


def time_to_hire(db, tenant, scope, as_of: date) -> dict:
    rows = db.query(Application.created_at, Application.updated_at).filter(Application.tenant_id == tenant.tenant_id, Application.status == "hired").all()
    days = [(u - c).days for c, u in rows if c and u]
    return {"value": round(sum(days) / len(days), 1) if days else None, "unit": "days", "hires": len(days)}


def cost_per_hire(db, tenant, scope, as_of: date) -> dict:
    spend = SettingsService(db).get("analytics.recruiting_spend_ytd", SettingContext(tenant=tenant))
    hires = time_to_hire(db, tenant, scope, as_of)["hires"]
    if not spend:
        return {"value": None, "reason": "set analytics.recruiting_spend_ytd to compute cost-per-hire"}
    return {"value": round(float(Decimal(str(spend)) / hires), 2) if hires else None, "hires": hires}


def offer_acceptance(db, tenant, scope, as_of: date) -> dict:
    total = db.query(func.count(Offer.id)).filter(Offer.tenant_id == tenant.tenant_id).scalar() or 0
    signed = db.query(func.count(Offer.id)).filter(Offer.tenant_id == tenant.tenant_id, Offer.signed.is_(True)).scalar() or 0
    return {"value": round(100 * signed / total, 1) if total else None, "unit": "%", "offers": total}


def bgv_turnaround(db, tenant, scope, as_of: date) -> dict:
    rows = db.query(BgvCase.initiated_at, BgvCase.completed_at).filter(BgvCase.tenant_id == tenant.tenant_id, BgvCase.completed_at.isnot(None), BgvCase.initiated_at.isnot(None)).all()
    days = [(c - i).total_seconds() / 86400 for i, c in rows]
    return {"value": round(sum(days) / len(days), 1) if days else None, "unit": "days"}


def onboarding_readiness(db, tenant, scope, as_of: date) -> dict:
    from app.onboarding.portal import PreboardingPortal

    portal = PreboardingPortal(db, tenant)
    cases = _scoped(db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status.in_(("invited", "in_progress", "ready")),
                                                     PreboardingCase.joining_date.between(as_of, as_of + timedelta(days=30))), PreboardingCase.employee_id, scope).all()
    values = [portal.readiness(c)["percent"] for c in cases]
    return {"value": round(sum(values) / len(values), 1) if values else None, "unit": "%", "joiners": len(values)}


def ticket_sla(db, tenant, scope, as_of: date) -> dict:
    q = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.resolved_at.isnot(None), Ticket.resolution_due_at.isnot(None), Ticket.confidential.is_(False))
    rows = _scoped(q, Ticket.requester_employee_id, scope).all()
    met = sum(1 for t in rows if t.resolved_at <= t.resolution_due_at)
    return {"value": round(100 * met / len(rows), 1) if rows else None, "unit": "%", "resolved": len(rows)}


def asset_allocation(db, tenant, scope, as_of: date) -> dict:
    total = db.query(func.count(Asset.id)).filter(Asset.tenant_id == tenant.tenant_id, Asset.status.in_(("in_stock", "allocated"))).scalar() or 0
    allocated = db.query(func.count(Asset.id)).filter(Asset.tenant_id == tenant.tenant_id, Asset.status == "allocated").scalar() or 0
    return {"value": round(100 * allocated / total, 1) if total else None, "unit": "%"}


def goal_completion(db, tenant, scope, as_of: date) -> dict:
    q = _scoped(db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.status.in_(("active", "completed"))), Goal.owner_employee_id, scope)
    goals = q.all()
    done = sum(1 for g in goals if g.status == "completed")
    return {"value": round(100 * done / len(goals), 1) if goals else None, "unit": "%"}


_FUNCS = {name: globals()[name] for name in METRICS}


def compute(db: Session, tenant: TenantContext, metric: str, *, scope: Optional[set[UUID]] = None, as_of: Optional[date] = None) -> dict:
    if metric not in _FUNCS:
        raise KeyError(metric)
    return {"metric": metric, **_FUNCS[metric](db, tenant, scope, as_of or datetime.now(timezone.utc).date())}
