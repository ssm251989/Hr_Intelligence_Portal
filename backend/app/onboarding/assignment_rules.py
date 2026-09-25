"""assignment_rules evaluation (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 4) -- JSONLogic
conditions over a conversion context, evaluated with the same `json_logic` library Part 4's
NotificationRuleMatcher already uses (no second expression engine)."""

from typing import Optional

from sqlalchemy.orm import Session

import json_logic

from app.models.onboarding import ASSIGNMENT_TARGET_TYPES, AssignmentRule
from app.platform.tenancy.context import TenantContext


class InvalidAssignmentRuleError(ValueError):
    pass


def create_rule(
    db: Session, tenant: TenantContext, *, name: str, target_type: str, target_ref: str,
    condition_jsonlogic: Optional[dict] = None, priority: int = 100,
) -> AssignmentRule:
    if target_type not in ASSIGNMENT_TARGET_TYPES:
        raise InvalidAssignmentRuleError(f"unknown target_type {target_type!r}")
    if condition_jsonlogic is not None:
        try:
            json_logic.jsonLogic(condition_jsonlogic, {})
        except Exception as exc:  # malformed operator etc -- reject at write time, not at conversion time
            raise InvalidAssignmentRuleError(f"invalid condition: {exc}") from exc
    rule = AssignmentRule(
        tenant_id=tenant.tenant_id, name=name, target_type=target_type, target_ref=target_ref,
        condition_jsonlogic=condition_jsonlogic, priority=priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _matches(rule: AssignmentRule, ctx: dict) -> bool:
    if rule.condition_jsonlogic is None:
        return True
    try:
        return bool(json_logic.jsonLogic(rule.condition_jsonlogic, ctx))
    except Exception:
        return False  # a rule that can't evaluate against this context never assigns anything


def matching_rules(db: Session, tenant: TenantContext, target_type: str, ctx: dict) -> list[AssignmentRule]:
    rules = (
        db.query(AssignmentRule)
        .filter(AssignmentRule.tenant_id == tenant.tenant_id, AssignmentRule.target_type == target_type, AssignmentRule.is_active.is_(True))
        .order_by(AssignmentRule.priority.asc(), AssignmentRule.created_at.asc())
        .all()
    )
    return [r for r in rules if _matches(r, ctx)]


def resolve_one(db: Session, tenant: TenantContext, target_type: str, ctx: dict) -> Optional[str]:
    """Single-valued targets (a plan template, a letter template): the lowest-priority
    matching rule's target_ref, or None."""
    rules = matching_rules(db, tenant, target_type, ctx)
    return rules[0].target_ref if rules else None


def resolve_all(db: Session, tenant: TenantContext, target_type: str, ctx: dict) -> list[str]:
    """Additive targets (roles): every matching rule's target_ref, de-duplicated, in order."""
    seen: list[str] = []
    for rule in matching_rules(db, tenant, target_type, ctx):
        if rule.target_ref not in seen:
            seen.append(rule.target_ref)
    return seen
