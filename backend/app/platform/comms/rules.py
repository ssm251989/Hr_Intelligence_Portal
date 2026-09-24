"""NotificationRuleMatcher (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 3)."""

from typing import Optional

from sqlalchemy.orm import Session

try:
    import json_logic
except ImportError:  # pragma: no cover
    json_logic = None

from app.models.comms import NotificationRule
from app.platform.tenancy.context import TenantContext


def _condition_passes(condition: Optional[dict], ctx: dict) -> bool:
    if condition is None:
        return True
    if json_logic is None:
        return False
    return bool(json_logic.jsonLogic(condition, ctx))


class NotificationRuleMatcher:
    def __init__(self, db: Session):
        self.db = db

    def match(self, tenant: TenantContext, event_type: str, event_ctx: dict) -> list[NotificationRule]:
        rules = (
            self.db.query(NotificationRule)
            .filter(NotificationRule.tenant_id == tenant.tenant_id, NotificationRule.event_type == event_type, NotificationRule.enabled.is_(True))
            .order_by(NotificationRule.priority.asc())
            .all()
        )
        return [rule for rule in rules if _condition_passes(rule.condition_jsonlogic, event_ctx)]
