"""Setup Wizard (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 1; decision A5: our team runs
`hrctl`, the client's admin finishes here).

Steps: company -> entities & locations -> branding -> connect mailbox (test) -> import
employees -> pick modules -> pick config pack -> invite admins. Progress is DERIVED from
real data (a step is done because the thing exists, not because someone clicked "next"),
so the checklist on the admin home can't drift from reality. A step can be explicitly
skipped (recorded in `platform.setup.skipped`) -- Part 17.10: a skipped step is shown as
skipped, never as done; only a real save turns a step green.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.comms import BrandTheme
from app.models.connection import Connection, ConnectionRoute
from app.models.core_hr import Employee, LegalEntity, Location
from app.models.user import User
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

# Part 18.21: "Start from a ready-made template" and "Invite another admin" are no longer setup
# steps (owner decision). Their functions/endpoints stay for API use; admins are added in
# Settings > People & access.
STEPS = ("company", "entities_locations", "branding", "mailbox", "import_employees", "modules")
SKIPPABLE = {"branding", "import_employees", "modules"}
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
        "config_pack": (_has_tenant_value(db, tenant, "platform.setup.config_pack"), "A ready-made template was applied."),
        "invite_admins": (admins >= 2, f"{admins} admin(s) -- invite at least one more so you're never locked out."),
    }
    from app.platform.modules import enabled_modules

    on = enabled_modules(db, tenant)
    steps = []
    for step in STEPS:
        if step == "import_employees" and "core_hr" not in on:
            continue  # Part 18.5: no employee records module -> no "import employees" step
        done, detail = checks[step]
        steps.append({"step": step, "done": bool(done), "skipped": step in skipped and not done, "detail": detail,
                      "skippable": step in SKIPPABLE, "fix_path": _FIX_PATHS[step]})
    complete = sum(1 for s in steps if s["done"])
    settled = sum(1 for s in steps if s["done"] or s["skipped"])
    return {"steps": steps, "percent": round(100 * complete / max(1, len(steps))), "complete": settled == len(steps),
            "done_count": complete, "skipped_count": settled - complete}


def values(db: Session, tenant: TenantContext) -> dict:
    """Part 17.10: what is saved for each step, so a reopened step shows it and can edit it."""
    from app.models.experience import TenantMedia

    s, ctx = SettingsService(db), SettingContext(tenant=tenant)
    theme = db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()
    logo = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == "brand.logo").first()
    mailbox_ok, mailbox_detail = _mailbox_state(db, tenant)
    return {
        "company": {k.split(".")[1]: s.get(k, ctx) for k in ("org.display_name", "org.legal_name", "org.timezone", "org.locale", "org.currency")},
        "entities": [{"id": str(e.id), "name": e.name} for e in db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id).order_by(LegalEntity.name)],
        "locations": [{"id": str(l.id), "name": l.name, "state": l.state, "lat": l.geo_lat, "lng": l.geo_lng}
                      for l in db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name)],
        "branding": {"primary_color": theme.primary_color if theme else None, "secondary_color": theme.secondary_color if theme else None,
                     "logo_url": f"/api/v1/public/media/brand.logo?v={int(logo.updated_at.timestamp())}" if logo and logo.updated_at else None},
        "mailbox": {"connected": mailbox_ok, "detail": mailbox_detail},
        "employees": {"count": db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).count()},
        "modules": s.get("platform.modules.enabled", ctx) or [],
        "available_modules": available_modules(db, tenant),  # Part 18.5
        "template": s.get("platform.setup.config_pack", ctx) or None,
        "admins": [{"email": u.email, "name": u.full_name} for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").order_by(User.created_at)],
    }


def add_entity_location(db: Session, tenant: TenantContext, *, entity_name: str, location_name: str, city: Optional[str],
                        state: Optional[str], actor: str) -> dict:
    """First legal entity + office from the wizard (re-uses an entity of the same name)."""
    from app.platform.geo.service import offline

    entity_name, location_name = entity_name.strip(), location_name.strip()
    if not entity_name or not location_name:
        raise SetupError("Give the company's legal name and the office name.")
    entity = db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id, LegalEntity.name == entity_name).first()
    if entity is None:
        entity = LegalEntity(tenant_id=tenant.tenant_id, name=entity_name)
        db.add(entity)
        db.commit()
        db.refresh(entity)
    place = offline(city or location_name)
    loc = db.query(Location).filter(Location.tenant_id == tenant.tenant_id, Location.name == location_name).first()
    if loc is None:
        loc = Location(tenant_id=tenant.tenant_id, name=location_name, legal_entity_id=entity.id)
        db.add(loc)
    loc.state = state or (place.label.split(", ")[-1] if place else None)
    if place is not None:
        loc.geo_lat, loc.geo_lng = f"{place.lat:.5f}", f"{place.lng:.5f}"
    db.commit()
    return progress(db, tenant)


EMPLOYEE_COLUMNS = {"first_name": "first_name", "last_name": "last_name", "personal_email": "personal_email", "personal_phone": "personal_phone",
                    "employee_code": "employee_code", "status": "status", "worker_type": "worker_type", "gender": "gender"}


def read_employee_file(data: bytes, filename: str) -> list[dict]:
    """CSV or XLSX with a header row; header names are matched loosely ("First name" -> first_name)."""
    import csv
    import io

    def norm(h) -> str:
        return str(h or "").strip().lower().replace(" ", "_").replace("-", "_")

    rows: list[dict] = []
    if filename.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [norm(h) for h in next(it, [])]
        for r in it:
            if r and any(v not in (None, "") for v in r):
                rows.append({header[i]: (str(v).strip() if v is not None else None) for i, v in enumerate(r) if i < len(header)})
    elif filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        for r in reader:
            rows.append({norm(k): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k})
    else:
        raise SetupError("Please upload a .csv or .xlsx file (download the sample file to start).")
    if not rows:
        raise SetupError("The file has no rows under the header.")
    if len(rows) > 5000:
        raise SetupError("Please upload at most 5,000 people at a time.")
    return rows


def import_employees(db: Session, tenant: TenantContext, data: bytes, filename: str, *, commit: bool, actor: str) -> dict:
    from app.core_hr.import_wizard import commit_batch, create_batch

    rows = read_employee_file(data, filename)
    present = {k for r in rows for k in r}
    mapping = {src: dst for src, dst in EMPLOYEE_COLUMNS.items() if src in present}
    if "first_name" not in mapping:
        raise SetupError("The file needs a 'first_name' column.")
    _keep_upload(tenant, data, filename)
    batch = create_batch(db, tenant, entity="employee", rows=rows, column_mapping=mapping, created_by=actor)
    result = {"batch_id": str(batch.id), "rows": batch.row_count, "errors": batch.error_count, "committed": 0}
    if commit:
        result.update(commit_batch(db, tenant, batch.id, created_by=actor))
        result["progress"] = progress(db, tenant)
    return result


def _keep_upload(tenant: TenantContext, data: bytes, filename: str) -> None:
    """The uploaded file itself is kept in storage (the storage connection, else local disk)."""
    import uuid as _uuid

    from app.experience.media_router import MEDIA_DIR, _storage

    ext = filename.rsplit(".", 1)[-1].lower()
    key = f"imports/{tenant.tenant_id}/{_uuid.uuid4()}.{ext}"
    storage = _storage()
    if storage is not None and getattr(storage.put(key, data, "application/octet-stream"), "success", False):
        return
    path = MEDIA_DIR.parent / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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


def available_modules(db: Session, tenant: TenantContext, *, offered_only: bool = True) -> list[dict]:
    """Part 18.5: the modules that exist AND this company's licence allows; `offered_only` =
    only those the Setup checklist offers (platform.modules.offered)."""
    from app.platform.modules import MODULES, _licensed_modules

    s, ctx = SettingsService(db), SettingContext(tenant=tenant)
    offered = set(s.get("platform.modules.offered", ctx) or [])
    wanted = set(s.get("platform.modules.enabled", ctx) or [])
    licensed = _licensed_modules(tenant)
    return [{"code": m.code, "on": m.code in wanted, "offered": m.code in offered}
            for m in MODULES if not m.always_on and (licensed is None or m.code in licensed) and (not offered_only or m.code in offered)]


def set_modules(db: Session, tenant: TenantContext, modules: list[str], *, actor: str, scope: str = "offered") -> dict:
    """Setup's "Choose what you use" saves only the modules it offers (the others keep their
    state); Settings > Modules (`scope="all"`) can switch any allowed module."""
    allowed = {m["code"] for m in available_modules(db, tenant, offered_only=(scope != "all"))}
    unknown = sorted(set(modules) - allowed)
    if unknown:
        raise SetupError(f"These modules can't be switched on here: {', '.join(unknown)}")
    current = set(SettingsService(db).get("platform.modules.enabled", SettingContext(tenant=tenant)) or [])
    new = (current - allowed) | set(modules)
    SettingsService(db).set("platform.modules.enabled", sorted(new), scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    from app.platform import module_lock

    module_lock.invalidate(tenant.tenant_id)
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
