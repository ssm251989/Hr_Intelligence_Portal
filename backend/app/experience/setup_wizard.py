"""Setup Wizard (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 1; decision A5: our team runs
`hrctl`, the client's admin finishes here).

Steps: company -> entities & locations -> branding -> connect mailbox (test) -> import
employees -> pick modules -> pick config pack -> invite admins. Progress is DERIVED from
real data (a step is done because the thing exists, not because someone clicked "next"),
so the checklist on the admin home can't drift from reality. A step can be explicitly
skipped (recorded in `platform.setup.skipped`), which counts as done.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.comms import BrandTheme
from app.models.connection import Connection, ConnectionRoute
from app.models.core_hr import Employee, LegalEntity, Location
from app.models.user import User
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

STEPS = ("company", "entities_locations", "branding", "mailbox", "import_employees", "modules", "config_pack", "invite_admins")
SKIPPABLE = {"branding", "import_employees", "config_pack", "invite_admins", "modules"}
_FIX_PATHS = {
    "company": "/setup?step=company", "entities_locations": "/setup?step=entities_locations", "branding": "/setup?step=branding",
    "mailbox": "/setup?step=mailbox", "import_employees": "/setup?step=import_employees", "modules": "/setup?step=modules",
    "config_pack": "/setup?step=config_pack", "invite_admins": "/setup?step=invite_admins",
}


class SetupError(ValueError):
    pass


def _has_tenant_value(db: Session, tenant: TenantContext, key: str) -> bool:
    from app.models.setting_value import SettingValue

    return db.query(SettingValue).filter(SettingValue.tenant_id == tenant.tenant_id, SettingValue.key == key, SettingValue.scope_type == "tenant").first() is not None


def _mailbox_state(db: Session, tenant: TenantContext) -> tuple[bool, str]:
    route = (
        db.query(ConnectionRoute)
        .filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.purpose == "email.outbound.default", ConnectionRoute.enabled.is_(True))
        .first()
    )
    if route is None:
        return False, "No mailbox is connected for outgoing email yet."
    connection = db.get(Connection, route.connection_id)
    if connection is None or connection.status != "active":
        return False, "The outgoing mailbox connection isn't active."
    if not (connection.last_test_result or {}).get("success"):
        return False, "Send a test email to confirm the mailbox works."
    return True, "Mailbox connected and tested."


def progress(db: Session, tenant: TenantContext) -> dict:
    settings = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    skipped = set(settings.get("platform.setup.skipped", ctx) or [])
    mailbox_ok, mailbox_detail = _mailbox_state(db, tenant)
    admins = db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").count()
    checks = {
        "company": (_has_tenant_value(db, tenant, "org.display_name") and _has_tenant_value(db, tenant, "org.timezone"), "Company name and timezone set."),
        "entities_locations": (db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id).count() > 0
                               and db.query(Location).filter(Location.tenant_id == tenant.tenant_id).count() > 0, "At least one legal entity and one location."),
        "branding": (db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).count() > 0, "A default brand theme exists."),
        "mailbox": (mailbox_ok, mailbox_detail),
        "import_employees": (db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).count() > 0, "Employees imported."),
        "modules": (_has_tenant_value(db, tenant, "platform.modules.enabled"), "Modules chosen."),
        "config_pack": (_has_tenant_value(db, tenant, "platform.setup.config_pack"), "A configuration pack was applied."),
        "invite_admins": (admins >= 2, f"{admins} admin(s) -- invite at least one more so you're never locked out."),
    }
    steps = []
    for step in STEPS:
        done, detail = checks[step]
        steps.append({"step": step, "done": bool(done) or step in skipped, "skipped": step in skipped and not done, "detail": detail,
                      "skippable": step in SKIPPABLE, "fix_path": _FIX_PATHS[step]})
    complete = sum(1 for s in steps if s["done"])
    return {"steps": steps, "percent": round(100 * complete / len(steps)), "complete": complete == len(steps)}


def skip(db: Session, tenant: TenantContext, step: str, *, actor: str, undo: bool = False) -> dict:
    if step not in STEPS:
        raise SetupError(f"unknown step {step!r}")
    if step not in SKIPPABLE and not undo:
        raise SetupError(f"'{step}' can't be skipped -- the product doesn't work without it")
    settings = SettingsService(db)
    current = set(settings.get("platform.setup.skipped", SettingContext(tenant=tenant)) or [])
    current = current - {step} if undo else current | {step}
    settings.set("platform.setup.skipped", sorted(current), scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return progress(db, tenant)


def set_company(db: Session, tenant: TenantContext, *, display_name: str, legal_name: Optional[str], timezone: str, locale: Optional[str],
                currency: Optional[str], actor: str) -> dict:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(timezone)
    except Exception:
        raise SetupError(f"unknown timezone {timezone!r}")
    settings = SettingsService(db)
    for key, value in (("org.display_name", display_name), ("org.legal_name", legal_name or display_name), ("org.timezone", timezone),
                       ("org.locale", locale), ("org.currency", currency)):
        if value:
            settings.set(key, value, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return progress(db, tenant)


def set_modules(db: Session, tenant: TenantContext, modules: list[str], *, actor: str) -> dict:
    from app.platform.modules import MODULES

    known = {m.code for m in MODULES if not m.always_on}
    unknown = sorted(set(modules) - known)
    if unknown:
        raise SetupError(f"unknown module(s): {', '.join(unknown)}")
    SettingsService(db).set("platform.modules.enabled", sorted(set(modules)), scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return progress(db, tenant)


def apply_config_pack(db: Session, tenant: TenantContext, pack: dict, *, actor: str, dry_run: bool) -> dict:
    from app.platform.config_pack import ConfigPackError, import_pack

    try:
        report = import_pack(db, tenant, pack, actor=actor, dry_run=dry_run)
    except ConfigPackError as exc:
        raise SetupError(str(exc)) from exc
    if not dry_run:
        SettingsService(db).set("platform.setup.config_pack", {"source": pack.get("source_tenant"), "exported_at": pack.get("exported_at")},
                                scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return report


def invite_admin(db: Session, tenant: TenantContext, *, email: str, full_name: Optional[str], actor: str) -> dict:
    """Creates the admin with an unusable password and sends a one-time set-password link
    through the tenant's OWN mailbox (decision D2) using its `platform.admin_invite`
    template. If mail can't go out, the link is returned so the admin can share it."""
    import secrets

    from app.core.config import settings as app_settings
    from app.core.security import hash_password
    from app.platform.comms.service import send
    from app.platform.iam.action_tokens import create_action_token
    from app.platform.iam.roles import bridge_single_user

    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise SetupError("a user with this email already exists")
    user = User(tenant_id=tenant.tenant_id, email=email, full_name=full_name or email, role="admin", hashed_password=hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    db.commit()
    db.refresh(user)
    bridge_single_user(db, tenant, user)
    token = create_action_token(db, tenant, entity_type="user", entity_id=user.id, action="set_password", created_by=actor, ttl_days=7).token
    link = f"{app_settings.FRONTEND_URL.rstrip('/')}/set-password?token={token}"
    try:
        message = send(db, tenant, template_key="platform.admin_invite", to=[email], ctx={"link": link, "invited_by": actor}, purpose="email.outbound.default")
        delivered = message.status in ("sent", "queued")
    except Exception:
        delivered = False
    return {"user_id": str(user.id), "email_sent": delivered, "link": None if delivered else link}
