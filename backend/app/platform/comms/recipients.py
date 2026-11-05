"""RecipientResolver (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 1's recipients_json
shapes). A pluggable registry keyed by "relation"/top-level key, since several shapes
(employee.manager, role+scope) need Core HR's org model (Part 7) to resolve for real --
registered here with a clear NotImplementedError rather than silently resolving to
nothing, so a rule using one fails loudly at dispatch time, not silently sends to nobody.
"""

from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


class RecipientResolutionError(Exception):
    pass


_RELATION_RESOLVERS: dict[str, Callable[[Session, TenantContext, dict, dict], list[str]]] = {}


def register_relation_resolver(relation: str, resolver: Callable[[Session, TenantContext, dict, dict], list[str]]) -> None:
    _RELATION_RESOLVERS[relation] = resolver


def _resolve_relation(db: Session, tenant: TenantContext, spec: dict, event_ctx: dict) -> list[str]:
    relation = spec["relation"]
    resolver = _RELATION_RESOLVERS.get(relation)
    if resolver is None:
        raise RecipientResolutionError(f"Can't work out who the {relation.replace('_', ' ')} is: employee records (People) aren't set up.")
    return resolver(db, tenant, spec, event_ctx)


def _resolve_users(db: Session, tenant: TenantContext, spec: dict, event_ctx: dict) -> list[str]:
    from app.models.user import User

    ids_or_emails = spec["users"]
    emails: list[str] = []
    for value in ids_or_emails:
        try:
            user = db.get(User, UUID(str(value)))
            if user is not None:
                emails.append(user.email)
                continue
        except (ValueError, TypeError):
            pass
        emails.append(str(value))  # already a plain email
    return emails


def _resolve_emails_setting(db: Session, tenant: TenantContext, spec: dict, event_ctx: dict) -> list[str]:
    service = SettingsService(db)
    value = service.get(spec["emails_setting"], SettingContext(tenant=tenant))
    if value is None:
        return []
    if isinstance(value, str):
        return [addr.strip() for addr in value.split(",") if addr.strip()]
    if isinstance(value, list):
        return list(value)
    return []


def _resolve_expression(db: Session, tenant: TenantContext, spec: dict, event_ctx: dict) -> list[str]:
    import json_logic

    result = json_logic.jsonLogic(spec["expression"], event_ctx)
    if isinstance(result, str):
        return [result]
    if isinstance(result, list):
        return [str(item) for item in result]
    return []


# relation:candidate / relation:application.interviewers are resolved directly from the
# triggering event's own context (event_ctx) -- the caller (dispatch.py) is expected to
# put whatever the event naturally already has (candidate_email, interviewer_emails, ...)
# there, since there's no separate lookup needed for data the event itself carries.
def _resolve_from_event_ctx(key: str):
    def _resolver(db: Session, tenant: TenantContext, spec: dict, event_ctx: dict) -> list[str]:
        value = event_ctx.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    return _resolver


register_relation_resolver("candidate", _resolve_from_event_ctx("candidate_email"))
register_relation_resolver("application.interviewers", _resolve_from_event_ctx("interviewer_emails"))


class RecipientResolver:
    def __init__(self, db: Session, tenant: TenantContext):
        self.db = db
        self.tenant = tenant

    def resolve(self, recipients_spec: dict, event_ctx: dict) -> list[str]:
        if "relation" in recipients_spec:
            return _resolve_relation(self.db, self.tenant, recipients_spec, event_ctx)
        if "users" in recipients_spec:
            return _resolve_users(self.db, self.tenant, recipients_spec, event_ctx)
        if "emails_setting" in recipients_spec:
            return _resolve_emails_setting(self.db, self.tenant, recipients_spec, event_ctx)
        if "expression" in recipients_spec:
            return _resolve_expression(self.db, self.tenant, recipients_spec, event_ctx)
        if "role" in recipients_spec:
            raise RecipientResolutionError("Sending to a role needs roles set up in Settings > People > Roles.")
        raise RecipientResolutionError(f"Unrecognized recipients_json shape: {list(recipients_spec.keys())}")
