"""Goals & OKRs (docs/HRMS_COMPLETE_SPEC.txt Part 10 section A): cascading goals with an
alignment tree, weightage rules, measurable KPIs, check-ins, and auto-progress from an
integration webhook (matched on `external_ref`)."""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.performance import GOAL_LEVELS, Goal, GoalCheckin
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

_LEVEL_ORDER = {level: i for i, level in enumerate(GOAL_LEVELS)}


class GoalValidationError(ValueError):
    pass


def _weightage_rules(db: Session, tenant: TenantContext) -> dict:
    return SettingsService(db).get("performance.goals.weightage_rules", SettingContext(tenant=tenant)) or {}


def create_goal(
    db: Session, tenant: TenantContext, *, title: str, level: str = "individual", owner_employee_id: Optional[UUID] = None,
    parent_goal_id: Optional[UUID] = None, weightage: float = 0, kpi: Optional[dict] = None, cycle_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None, description: Optional[str] = None, external_ref: Optional[str] = None,
    library_code: Optional[str] = None, due_date=None,
) -> Goal:
    if level not in GOAL_LEVELS:
        raise GoalValidationError(f"unknown level {level!r}")
    if level == "individual" and owner_employee_id is None:
        raise GoalValidationError("an individual goal needs an owner")
    if parent_goal_id is not None:
        parent = db.get(Goal, parent_goal_id)
        if parent is None or parent.tenant_id != tenant.tenant_id:
            raise GoalValidationError("parent goal not found")
        if _LEVEL_ORDER[parent.level] > _LEVEL_ORDER[level]:
            raise GoalValidationError(f"a {level} goal cannot cascade from a {parent.level} goal")
    if kpi is not None and ("target" not in kpi or "metric" not in kpi):
        raise GoalValidationError("a KPI needs at least a metric and a target")
    rules = _weightage_rules(db, tenant)
    if weightage and rules.get("min_per_goal") is not None and weightage < rules["min_per_goal"]:
        raise GoalValidationError(f"each goal needs at least {rules['min_per_goal']}% weightage")
    goal = Goal(
        tenant_id=tenant.tenant_id, title=title, level=level, owner_employee_id=owner_employee_id, parent_goal_id=parent_goal_id,
        weightage=weightage, kpi_json=kpi, cycle_id=cycle_id, department_id=department_id, description=description,
        external_ref=external_ref, library_code=library_code, due_date=due_date,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def employee_goals(db: Session, tenant: TenantContext, employee_id: UUID, *, cycle_id: Optional[UUID] = None) -> list[Goal]:
    query = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.owner_employee_id == employee_id, Goal.status != "cancelled")
    if cycle_id is not None:
        query = query.filter(Goal.cycle_id == cycle_id)
    return query.order_by(Goal.created_at.asc()).all()


def validate_weightage(db: Session, tenant: TenantContext, employee_id: UUID, *, cycle_id: Optional[UUID] = None) -> dict:
    """Weightage rules (setting `performance.goals.weightage_rules`): total must equal
    `total` (default 100), goal count within [min_goals, max_goals]."""
    rules = {"total": 100, **_weightage_rules(db, tenant)}
    goals = employee_goals(db, tenant, employee_id, cycle_id=cycle_id)
    total = sum((Decimal(str(g.weightage or 0)) for g in goals), Decimal(0))
    problems = []
    if total != Decimal(str(rules["total"])):
        problems.append(f"weightage totals {total}, must be {rules['total']}")
    if rules.get("min_goals") is not None and len(goals) < rules["min_goals"]:
        problems.append(f"at least {rules['min_goals']} goals required")
    if rules.get("max_goals") is not None and len(goals) > rules["max_goals"]:
        problems.append(f"at most {rules['max_goals']} goals allowed")
    return {"valid": not problems, "total": float(total), "goal_count": len(goals), "problems": problems}


def kpi_progress(kpi: dict, current_value: float) -> float:
    """Progress % from a measurable KPI: linear between baseline and target, clamped 0-100.
    Works for 'decrease' KPIs too (target below baseline) since the ratio's sign flips."""
    baseline = float(kpi.get("baseline", 0) or 0)
    target = float(kpi["target"])
    if target == baseline:
        return 100.0 if current_value == target else 0.0
    pct = (current_value - baseline) / (target - baseline) * 100
    return max(0.0, min(100.0, round(pct, 2)))


def check_in(
    db: Session, tenant: TenantContext, goal: Goal, *, progress_pct: Optional[float] = None, current_value: Optional[float] = None,
    confidence: Optional[int] = None, comment: Optional[str] = None, actor: str = "system", source: str = "manual",
) -> GoalCheckin:
    if progress_pct is None:
        if current_value is None or not goal.kpi_json:
            raise GoalValidationError("give progress_pct, or current_value for a goal with a KPI")
        progress_pct = kpi_progress(goal.kpi_json, current_value)
    if not 0 <= progress_pct <= 100:
        raise GoalValidationError("progress must be between 0 and 100")
    if confidence is not None and not 1 <= confidence <= 5:
        raise GoalValidationError("confidence is 1-5")
    checkin = GoalCheckin(
        tenant_id=tenant.tenant_id, goal_id=goal.id, progress_pct=progress_pct, current_value=current_value,
        confidence=confidence, comment=comment, source=source, created_by=actor,
    )
    db.add(checkin)
    goal.progress_pct = progress_pct
    if confidence is not None:
        goal.confidence = confidence
    if progress_pct >= 100 and goal.status == "active":
        goal.status = "completed"
    db.commit()
    db.refresh(checkin)
    return checkin


def apply_integration_progress(
    db: Session, tenant: TenantContext, *, external_ref: str, current_value: Optional[float] = None, progress_pct: Optional[float] = None,
) -> list[GoalCheckin]:
    """Auto-progress from a connection webhook (e.g. Jira/CRM): every active goal carrying
    this external_ref gets an integration-sourced check-in."""
    goals = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.external_ref == external_ref, Goal.status == "active").all()
    return [check_in(db, tenant, g, progress_pct=progress_pct, current_value=current_value, actor="integration", source="integration") for g in goals]


def alignment_tree(db: Session, tenant: TenantContext, root_id: Optional[UUID] = None) -> list[dict]:
    goals = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.status != "cancelled").all()
    children: dict = {}
    for g in goals:
        children.setdefault(g.parent_goal_id, []).append(g)

    def _node(g: Goal, depth: int = 0) -> dict:
        kids = children.get(g.id, []) if depth < 10 else []
        node = {
            "id": str(g.id), "title": g.title, "level": g.level, "progress_pct": float(g.progress_pct or 0),
            "owner_employee_id": str(g.owner_employee_id) if g.owner_employee_id else None,
            "children": [_node(k, depth + 1) for k in kids],
        }
        if kids:  # a parent's rolled-up progress is the mean of its children's
            node["rolled_up_progress_pct"] = round(sum(c["progress_pct"] for c in node["children"]) / len(kids), 2)
        return node

    return [_node(g) for g in children.get(root_id, [])]


def goal_to_dict(g: Goal) -> dict:
    return {
        "id": str(g.id), "title": g.title, "description": g.description, "level": g.level,
        "parent_goal_id": str(g.parent_goal_id) if g.parent_goal_id else None,
        "owner_employee_id": str(g.owner_employee_id) if g.owner_employee_id else None,
        "cycle_id": str(g.cycle_id) if g.cycle_id else None, "weightage": float(g.weightage or 0), "kpi": g.kpi_json,
        "progress_pct": float(g.progress_pct or 0), "confidence": g.confidence, "status": g.status, "external_ref": g.external_ref,
    }
