"""Part 20.2 / 20.2b: company mailboxes for employees, through the email-admin connection.

The connection routed for purpose `directory.mailboxes` decides who creates the mailbox:
- google_workspace / microsoft_365  -> the real provider (app/platform/connectors/providers/*)
- test_mailbox                      -> the TEST (dummy) provider: rows in `test_mailboxes`, nothing real (20.2b)
- nothing routed                    -> an IT to-do "Create mailbox <address> for <name> (joins <date>)" with a
                                       "Done - mailbox created" button
The address comes from Settings > Onboarding & employees (pattern + domain, fallbacks when taken) and is
always checked free: not used by any employee or app login here, and free at the provider.
"""

import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Employee
from app.models.user import User

PURPOSE = "directory.mailboxes"
PROVIDERS = {"google_workspace": "google", "microsoft_365": "microsoft", "test_mailbox": "test"}


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _resolved(db: Session):
    from app.platform.connectors.router import ConnectorRouter

    return ConnectorRouter(db).try_resolve(PURPOSE)


def active_provider(db: Session, tenant) -> Optional[str]:
    """'test' | 'google' | 'microsoft' | None (IT to-do)."""
    r = _resolved(db)
    return PROVIDERS.get(r.connection.provider_code) if r is not None and r.connection.status == "active" else None


def adapter(db: Session, tenant):
    r = _resolved(db)
    if r is None or r.connection.status != "active":
        return None
    from app.platform.connectors.registry import get_provider

    spec = get_provider(r.connection.provider_code)
    if spec.adapter_cls is None:
        return None
    secrets: dict = {}
    if r.connection.secret_ref:
        import json

        from app.models.secret import Secret, SecretScope
        from app.platform.secrets.store import get_secret_store

        secrets = json.loads(get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id)).get(r.connection.secret_ref))
    return spec.adapter_cls(r.connection.config_json or {}, secrets)


# ---- addresses ----


def domain(db: Session, tenant) -> str:
    """Settings domain; else the domain the company's admins sign in with."""
    d = (_setting(db, tenant, "employees.email.domain") or "").strip().lower().lstrip("@")
    if d:
        return d
    admin = db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin", User.email.notlike("%@example.com")).order_by(User.created_at).first()
    return admin.email.split("@", 1)[1].lower() if admin and "@" in admin.email else "example.com"


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _render(pattern: str, first: str, last: str, n: int = 0) -> str:
    f, la = _slug(first), _slug(last)
    out = (pattern.replace("{first}", f).replace("{last}", la).replace("{f}", f[:1]).replace("{l}", la[:1])
           .replace("{n}", str(n) if n else ""))
    out = re.sub(r"\.+", ".", out).strip(".")
    return out


def address_options(db: Session, tenant, first: str, last: str) -> list[str]:
    patterns = [_setting(db, tenant, "employees.email.pattern") or "{first}.{last}", *(_setting(db, tenant, "employees.email.fallbacks") or ["{first}.{l}", "{first}.{last}{n}"])]
    dom, out = domain(db, tenant), []
    for p in patterns:
        if "{n}" in p:
            out += [f"{_render(p, first, last, n)}@{dom}" for n in range(2, 10)]
        else:
            out.append(f"{_render(p, first, last)}@{dom}")
    return [a for a in dict.fromkeys(out) if a.split("@")[0]]


def used_here(db: Session, tenant, address: str, *, except_employee_id=None) -> bool:
    address = address.lower()
    q = db.query(Employee.id).filter(Employee.tenant_id == tenant.tenant_id, Employee.company_email == address)
    if except_employee_id is not None:
        q = q.filter(Employee.id != except_employee_id)
    if q.first() is not None:
        return True
    user = db.query(User).filter(User.email == address).first()
    if user is None:
        return False
    if except_employee_id is not None:
        e = db.get(Employee, except_employee_id)
        if e is not None and e.user_id == user.id:
            return False
    return True


def is_free(db: Session, tenant, address: str, *, except_employee_id=None) -> tuple[bool, str]:
    address = (address or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", address):
        return False, "That isn't a valid email address."
    if used_here(db, tenant, address, except_employee_id=except_employee_id):
        return False, "Someone here already uses that address."
    a = adapter(db, tenant)
    if a is not None:
        try:
            if not a.is_free(address):
                return False, "That address already exists at the email provider."
        except Exception as exc:  # noqa: BLE001 -- can't check: say so, don't guess
            return False, f"Couldn't check with the email provider: {str(exc)[:150]}"
    return True, ""


def suggest(db: Session, tenant, first: str, last: str, *, except_employee_id=None) -> dict:
    tried = []
    for address in address_options(db, tenant, first, last):
        ok, why = is_free(db, tenant, address, except_employee_id=except_employee_id)
        if ok:
            return {"address": address, "tried": tried}
        tried.append({"address": address, "why": why})
    return {"address": None, "tried": tried}


# ---- create / suspend ----


def create(db: Session, tenant, e: Employee, address: str, *, joining: Optional[str], actor: str) -> dict:
    """-> {"mode": "provider", "provider", "address", "temp_password"?} or {"mode": "it_todo", "todo_id"}.
    A provider's one-time password is returned to show HR once -- never stored."""
    provider = active_provider(db, tenant)
    name = " ".join(p for p in (e.first_name, e.last_name) if p)
    if provider is None:
        todo = it_todo(db, tenant, e, "create", address, joining=joining, actor=actor)
        return {"mode": "it_todo", "provider": None, "address": address, "todo_id": str(todo.id)}
    result = adapter(db, tenant).create_mailbox(address=address, first_name=e.first_name, last_name=e.last_name or "", display_name=name,
                                                employee_ref=e.employee_code, actor=actor)
    e.company_email, e.company_email_provider = address, provider
    db.commit()
    log_action(db, "employee", e.id, "mailbox_created", actor[:50], {"address": address, "provider": provider})
    return {"mode": "provider", "provider": provider, "address": address, "temp_password": result.get("temp_password"), "note": result.get("note")}


def suspend(db: Session, tenant, e: Employee, *, actor: str) -> dict:
    if not e.company_email:
        return {"mode": "none"}
    provider = active_provider(db, tenant)
    if provider is None or (e.company_email_provider and e.company_email_provider != provider):
        todo = it_todo(db, tenant, e, "suspend", e.company_email, joining=None, actor=actor)
        return {"mode": "it_todo", "todo_id": str(todo.id)}
    adapter(db, tenant).suspend_mailbox(e.company_email, actor)
    log_action(db, "employee", e.id, "mailbox_suspended", actor[:50], {"address": e.company_email, "provider": provider})
    return {"mode": "provider", "provider": provider, "status": "suspended"}


def it_todo(db: Session, tenant, e: Employee, action: str, address: str, *, joining: Optional[str], actor: str):
    """One open IT to-do per employee + action (never duplicated)."""
    from app.models.intelligence import AgentSuggestion

    kind = "it_mailbox_create" if action == "create" else "it_mailbox_suspend"
    existing = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == kind,
                                                 AgentSuggestion.entity_id == e.id, AgentSuggestion.status == "pending").first())
    name = " ".join(p for p in (e.first_name, e.last_name) if p)
    title = (f"Create mailbox {address} for {name}" + (f" (joins {joining})" if joining else "")) if action == "create" else f"Suspend mailbox {address} ({name} has left)"
    if existing is not None:
        existing.title, existing.payload_json = title, {**(existing.payload_json or {}), "address": address}
        db.commit()
        return existing
    row = AgentSuggestion(tenant_id=tenant.tenant_id, agent="onboarding", kind=kind, title=title, entity_type="employee", entity_id=e.id,
                          reviewer_permission="core_hr.employee.edit",
                          payload_json={"address": address, "employee_id": str(e.id), "name": name, "employee_code": e.employee_code, "action": action})
    db.add(row)
    db.commit()
    log_action(db, "employee", e.id, f"it_todo_{kind}", actor[:50], {"address": address})
    return row


def confirm_it_todo(db: Session, tenant, todo, *, address: Optional[str], actor: str) -> dict:
    """IT/HR pressed "Done - mailbox created" (optionally with the address IT really used)."""
    from datetime import datetime, timezone

    e = db.get(Employee, todo.entity_id)
    if e is None:
        raise ValueError("That employee no longer exists.")
    payload = dict(todo.payload_json or {})
    if todo.kind == "it_mailbox_create":
        final = (address or payload.get("address") or "").strip().lower()
        ok, why = is_free(db, tenant, final, except_employee_id=e.id) if final != (e.company_email or "") else (True, "")
        if not ok:
            raise ValueError(why)
        e.company_email, e.company_email_provider = final, "manual"
        payload["address"] = final
    todo.status, todo.final_payload_json, todo.reviewed_by, todo.reviewed_at = "approved", payload, actor[:120], datetime.now(timezone.utc)
    db.commit()
    log_action(db, "employee", e.id, "mailbox_confirmed_by_it" if todo.kind == "it_mailbox_create" else "mailbox_suspend_confirmed",
               actor[:50], {"address": payload.get("address")})
    return {"employee_id": str(e.id), "address": payload.get("address"), "kind": todo.kind}
