"""Part 19.2 / 19.2b / 19.2c: switching modules on with an activation code sent to CTD Techs.

1. A company admin chooses modules and asks for activation -> the modules wait ("pending"),
   the request gets a number (ACT-2026-00012) and ONE code.
2. The code is CHECKED only against a bcrypt hash bound to this company + the exact module list
   (expires after ACTIVATION_CODE_DAYS, works once, 5 wrong tries -> 30 min lock + CTD Techs told).
   Decision (19.2b/c vs "store only a hash"): the code is ALSO kept encrypted in the control-plane
   SecretStore so escalations and retries send the SAME code and a CTD super-admin can "Show code"
   (audit-logged). It is never shown or sent to the company, and is deleted once used/cancelled.
3. The email goes to CTD Techs approvers by PRIORITY (activation_approvers, @ctdtechs.com only):
   Priority 1 first; not actioned within the escalation time -> Priority 2, then 3 (inactive /
   empty priorities skipped; nobody left -> "Not actioned"). Option: send to all priorities at once.
   Always through the PLATFORM mailbox (app/platform/platform_mail.py), never the company's.
4. A failed send never loses the request: it is retried in the background (1, 5, 15, 60 min, then
   hourly up to 24 h); a refused address moves on to the next priority; after 24 h it shows red
   "Email not delivered" in the console. The real reason goes to the request history and the log;
   the company only sees a friendly message with the request number and CTD Techs' contacts.
5. The company can resend (cooldown + daily limit) or cancel; CTD Techs can resend to a chosen
   priority or all, make a new code, show the code, cancel.
Every send / resend / escalation / retry is in the request history (activation_events).
"""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.platform import module_registry as reg
from app.platform import platform_mail

log = logging.getLogger(__name__)

OWNER_DOMAIN = "ctdtechs.com"  # the platform owner; approvers can never be outside it
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes: 0/O, 1/I
CODE_LENGTH = 8
MAX_TRIES = 5
LOCK_MINUTES = 30
BACKOFF_MINUTES = (1, 5, 15, 60)  # then hourly
GIVE_UP_HOURS = 24
_EMAIL = re.compile(r"^[^@\s]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


class ActivationError(ValueError):
    def __init__(self, message: str, code: str = "ACTIVATION_ERROR", status_code: int = 400, **extra):
        super().__init__(message)
        self.code, self.status_code, self.extra = code, status_code, extra


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cp():
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal

    return ControlPlaneSessionLocal()


# ---------------------------------------------------------------- approvers (platform-level, by priority)

def _domain_allowed(domain: str) -> bool:
    domain = (domain or "").strip().lower()
    return domain == OWNER_DOMAIN or domain.endswith("." + OWNER_DOMAIN)


def validate_email(e: str, allowed_domain: Optional[str] = None) -> str:
    allowed = (allowed_domain or settings.ACTIVATION_ALLOWED_DOMAIN).strip().lower()
    if not _domain_allowed(allowed):
        raise ActivationError(f"ACTIVATION_ALLOWED_DOMAIN must be {OWNER_DOMAIN} (or under it), not {allowed!r}.", "APPROVER_NOT_ALLOWED")
    e = (e or "").strip().lower()
    if not _EMAIL.match(e):
        raise ActivationError(f"{e!r} isn't an email address.", "APPROVER_NOT_ALLOWED")
    domain = e.rsplit("@", 1)[1]
    if domain != allowed and not domain.endswith("." + allowed):
        raise ActivationError(f"{e} is not a {allowed} address. Activation codes only go to {allowed}.", "APPROVER_NOT_ALLOWED")
    return e


def validate_approvers(emails, allowed_domain: Optional[str] = None) -> list[str]:
    out = [validate_email(e, allowed_domain) for e in emails]
    if not out:
        raise ActivationError("At least one approver email is needed.", "APPROVER_NOT_ALLOWED")
    return out


def check_startup() -> None:
    """Called when the app starts: refuse to run with approver settings outside ctdtechs.com."""
    try:
        validate_approvers(settings.ACTIVATION_APPROVER_EMAILS)
    except ActivationError as exc:
        raise RuntimeError(f"Module activation is misconfigured: {exc}") from exc


def list_approvers() -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationApprover

    cp_db = _cp()
    try:
        return [{"priority": a.priority, "name": a.name, "email": a.email, "active": a.active,
                 "updated_by": a.updated_by, "updated_at": a.updated_at.isoformat() if a.updated_at else None}
                for a in cp_db.query(ActivationApprover).order_by(ActivationApprover.priority).all()]
    finally:
        cp_db.close()


def active_approvers() -> list[dict]:
    """Active approvers in priority order; each checked again here (refuse to send otherwise)."""
    out = []
    for a in list_approvers():
        if a["active"] and a["email"]:
            validate_email(a["email"])
            out.append(a)
    return out


def approvers() -> list[str]:
    """Emails of the active approvers in priority order (for display)."""
    return [a["email"] for a in active_approvers()]


def _audit(cp_db, actor: str, action: str, tenant_id=None, **details) -> None:
    from app.platform.tenancy.models_cp import SuperAdminAudit

    cp_db.add(SuperAdminAudit(admin_email=actor[:255], action=action, tenant_id=tenant_id, details_json=details))


def set_approver(priority: int, email: str, actor: str, *, name: Optional[str] = None, active: bool = True) -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationApprover

    if priority < 1 or priority > 20:
        raise ActivationError("Priority is 1 to 20.", "BAD_PRIORITY")
    email = validate_email(email)
    cp_db = _cp()
    try:
        row = cp_db.query(ActivationApprover).filter(ActivationApprover.priority == priority).first()
        old = {"name": row.name, "email": row.email, "active": row.active} if row is not None else None
        if row is None:
            row = ActivationApprover(priority=priority, email=email)
            cp_db.add(row)
        row.name, row.email, row.active, row.updated_by, row.updated_at = (name or "").strip() or None, email, bool(active), actor, _now()
        _audit(cp_db, actor, "activation_approver_set", priority=priority, old=old, new={"name": row.name, "email": email, "active": bool(active)})
        cp_db.commit()
    finally:
        cp_db.close()
    return list_approvers()


def remove_approver(priority: int, actor: str) -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationApprover

    cp_db = _cp()
    try:
        row = cp_db.query(ActivationApprover).filter(ActivationApprover.priority == priority).first()
        if row is None:
            raise ActivationError(f"There is no priority {priority} approver.", "NOT_FOUND", 404)
        _audit(cp_db, actor, "activation_approver_removed", priority=priority, old={"name": row.name, "email": row.email, "active": row.active}, new=None)
        cp_db.delete(row)
        cp_db.commit()
    finally:
        cp_db.close()
    return list_approvers()


def reorder_approvers(emails_in_order: list[str], actor: str) -> list[dict]:
    """Drag-to-reorder: the given emails become priorities 1, 2, 3 ... in that order."""
    from app.platform.tenancy.models_cp import ActivationApprover

    cp_db = _cp()
    try:
        rows = {r.email: r for r in cp_db.query(ActivationApprover).all()}
        if sorted(rows) != sorted(e.lower() for e in emails_in_order):
            raise ActivationError("The new order must list every approver exactly once.", "BAD_ORDER")
        old = {e: r.priority for e, r in rows.items()}
        for r in rows.values():  # step aside first (priority is unique)
            r.priority = r.priority + 1000
        cp_db.flush()
        for i, e in enumerate(emails_in_order, start=1):
            rows[e.lower()].priority, rows[e.lower()].updated_by, rows[e.lower()].updated_at = i, actor, _now()
        _audit(cp_db, actor, "activation_approvers_reordered", old=old, new={e.lower(): i for i, e in enumerate(emails_in_order, start=1)})
        cp_db.commit()
    finally:
        cp_db.close()
    return list_approvers()


# ---------------------------------------------------------------- codes

def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def pretty(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def normalise(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "").upper()


def _binding(code: str, tenant_id, modules) -> bytes:
    # sha256 first: bcrypt reads only 72 bytes, and the module list can be longer
    raw = f"{normalise(code)}|{tenant_id}|{','.join(sorted(modules))}"
    return hashlib.sha256(raw.encode()).hexdigest().encode()


def _hash(code: str, tenant_id, modules) -> str:
    import bcrypt

    return bcrypt.hashpw(_binding(code, tenant_id, modules), bcrypt.gensalt()).decode()


def _matches(code: str, req) -> bool:
    import bcrypt

    return bcrypt.checkpw(_binding(code, req.tenant_id, req.modules or []), req.code_hash.encode())


def _keep_code(cp_db, req, code: str) -> None:
    from app.platform.tenancy.provisioning import _store, put_or_rotate

    req.code_ref = f"activation-code-{req.id}"
    put_or_rotate(_store(cp_db), req.code_ref, code, created_by="activation")


def _kept_code(cp_db, req) -> Optional[str]:
    from app.platform.secrets.store import SecretNotFoundError
    from app.platform.tenancy.provisioning import _store

    if not req.code_ref:
        return None
    try:
        return _store(cp_db).get(req.code_ref)
    except SecretNotFoundError:
        return None


def _forget_code(cp_db, req) -> None:
    from app.platform.tenancy.provisioning import _store

    if req.code_ref:
        _store(cp_db).delete(req.code_ref)
        req.code_ref = None


def _next_number(cp_db) -> str:
    from sqlalchemy import text

    n = cp_db.execute(text("select nextval('activation_request_number_seq')")).scalar()
    return f"ACT-{_now().year}-{int(n):05d}"


# ---------------------------------------------------------------- helpers

def _company(db, tenant) -> tuple[str, str]:
    """(company name, installation/domain) for the email."""
    from app.platform.settings.resolver import SettingContext, SettingsService
    from app.platform.tenancy.models_cp import Tenant, TenantDomain

    name = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant))
    cp_db = _cp()
    try:
        t = cp_db.get(Tenant, tenant.tenant_id)
        hosts = [d.host for d in cp_db.query(TenantDomain).filter(TenantDomain.tenant_id == tenant.tenant_id).order_by(TenantDomain.is_primary.desc()).all()]
    finally:
        cp_db.close()
    name = name or (t.display_name if t is not None else tenant.slug)
    where = ", ".join(hosts) if hosts else settings.FRONTEND_URL
    return str(name), f"{where} (company {tenant.slug})"


def _names(keys) -> str:
    return ", ".join(reg.BY_KEY[k].name for k in keys if k in reg.BY_KEY)


def _fmt(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %H:%M IST") if dt else "-"


def _event(cp_db, req, kind: str, *, to=(), by: str, status: str, reason: Optional[str] = None) -> None:
    from app.platform.tenancy.models_cp import ActivationEvent

    cp_db.add(ActivationEvent(request_id=req.id, kind=kind, sent_to=list(to), by=by, status=status, reason=reason, at=_now()))


def _open_request(cp_db, tenant_id):
    from app.platform.tenancy.models_cp import ActivationRequest

    return (cp_db.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant_id, ActivationRequest.status == "pending")
            .order_by(ActivationRequest.created_at.desc()).first())


def _int_setting(key: str) -> int:
    """A number setting where 0 is a real value (e.g. no cooldown); missing -> the default."""
    value = platform_mail.get_setting(key)
    return int(value) if value is not None and str(value).strip() != "" else int(platform_mail.DEFAULTS[key])


def _support() -> dict:
    s = platform_mail.all_settings()
    return {"phone": s["support.phone"] or None, "email": s["support.email"] or None, "hours": s["support.hours"] or None}


# ---------------------------------------------------------------- sending

def _body(req, code: str, note: Optional[str]) -> tuple[str, str]:
    subject = f"Activation request {req.number} - {req.company_name} - {_names(req.modules)}"
    body = (
        (f"{note}\n\n" if note else "")
        + f"Request number: {req.number}\n"
        f"Company: {req.company_name}\n"
        f"Installation: {req.domain}\n"
        f"Requested by: {req.requested_by_name or '-'} <{req.requested_by_email or '-'}>\n"
        f"Modules: {_names(req.modules)}\n"
        f"Requested at: {_fmt(req.created_at)}\n\n"
        f"Activation code: {pretty(code)}\n"
        f"Valid until: {_fmt(req.expires_at)} (works once)\n\n"
        "Share this code with the company when they may use these modules. They enter it on\n"
        "Settings > Company > Modules.\n"
    )
    return subject, body


def _targets(req, *, priority: Optional[int] = None, everyone: bool = False) -> list[dict]:
    people = active_approvers()
    if everyone or (priority is None and platform_mail.get_setting("activation.send_all")):
        return people
    want = priority if priority is not None else (req.current_priority or (people[0]["priority"] if people else None))
    return [a for a in people if a["priority"] == want] or [a for a in people if a["priority"] > (want or 0)][:1]


def _deliver(cp_db, req, kind: str, by: str, *, priority: Optional[int] = None, everyone: bool = False, note: Optional[str] = None) -> bool:
    """Sends the request's code to the chosen approver(s). A refused address moves on to the next
    priority; any other failure is scheduled for a retry. Every attempt goes into the history."""
    code = _kept_code(cp_db, req)
    if code is None:  # made before codes were kept: retrying can't help -- CTD makes a new code
        reason = "No stored code for this request (made before codes were kept) -- use Generate new code."
        _event(cp_db, req, kind, by=by, status="failed", reason=reason)
        req.delivery, req.next_retry_at, req.email_error = "failed", None, reason
        return False
    try:
        targets = _targets(req, priority=priority, everyone=everyone)
    except ActivationError as exc:
        targets, bad = [], str(exc)
    else:
        bad = None
    while True:
        if not targets:
            reason = bad or "The approver list is empty (Super-admin console > Activation approvers)."
            _failed(req, kind, by, [], reason, cp_db)
            return False
        to = [a["email"] for a in targets]
        subject, body = _body(req, code, note)
        try:
            platform_mail.send(to, subject, body)
        except platform_mail.MailError as exc:
            log.warning("activation email %s (%s) to %s failed: %s", req.number, kind, to, exc.reason)
            if exc.recipient_refused and not everyone and priority is None:
                _event(cp_db, req, kind, to=to, by=by, status="failed", reason=exc.reason + " -- trying the next priority")
                later = [a for a in active_approvers() if a["priority"] > max(t["priority"] for t in targets)]
                targets = later[:1]
                if targets:
                    req.current_priority = targets[0]["priority"]
                continue
            _failed(req, kind, by, to, exc.reason, cp_db)
            platform_mail.set_last_test(False, exc.reason)
            return False
        now = _now()
        _event(cp_db, req, kind, to=to, by=by, status="sent")
        req.delivery, req.last_sent_at, req.next_retry_at, req.first_failed_at = "sent", now, None, None
        req.first_sent_at = req.first_sent_at or now
        req.emailed_at, req.emailed_to, req.email_error = now, to, None
        if not everyone and priority is None:
            req.current_priority = targets[0]["priority"]
        platform_mail.set_last_test(True, None)
        return True


def _failed(req, kind, by, to, reason, cp_db) -> None:
    now = _now()
    _event(cp_db, req, kind, to=to, by=by, status="failed", reason=reason)
    req.email_error = reason[:500]
    req.first_failed_at = req.first_failed_at or now
    if now - req.first_failed_at >= timedelta(hours=GIVE_UP_HOURS):
        req.delivery, req.next_retry_at = "failed", None
        return
    step = BACKOFF_MINUTES[req.retry_count] if req.retry_count < len(BACKOFF_MINUTES) else 60
    req.delivery, req.next_retry_at = "retrying", now + timedelta(minutes=step)


# ---------------------------------------------------------------- what the company sees

def request_info(req) -> Optional[dict]:
    """The company's view: never the code, never the technical reason."""
    if req is None:
        return None
    now = _now()
    status = "expired" if req.status == "pending" and req.expires_at < now else req.status
    cooldown = _int_setting("activation.resend_cooldown_minutes")
    per_day = _int_setting("activation.resend_max_per_day")
    today = now.date()
    used_today = req.resends_today if req.resend_day == today else 0
    next_at = req.last_resend_at + timedelta(minutes=cooldown) if req.last_resend_at else None
    return {"id": str(req.id), "number": req.number, "modules": list(req.modules or []), "status": status,
            "requested_at": req.created_at.isoformat() if req.created_at else None, "requested_by": req.requested_by_email,
            "expires_at": req.expires_at.isoformat(), "email_sent": req.first_sent_at is not None and req.delivery == "sent",
            "delivery": "sent" if req.delivery in ("sent", "not_actioned") else ("sending" if req.delivery == "sending" else "not_sent"),
            "sent_at": (req.last_sent_at or req.first_sent_at).isoformat() if (req.last_sent_at or req.first_sent_at) and req.delivery in ("sent", "not_actioned") else None,
            "first_sent_at": req.first_sent_at.isoformat() if req.first_sent_at else None, "resend_count": req.resend_count or 0,
            "resend_available_at": next_at.isoformat() if next_at and next_at > now else None,
            "resends_left_today": max(0, per_day - used_today),
            "locked_until": req.locked_until.isoformat() if req.locked_until and req.locked_until > now else None,
            "tries_left": MAX_TRIES - (req.attempts or 0), "support": _support()}


def open_request(tenant) -> Optional[dict]:
    """The waiting request; else the latest one if it expired (the page then offers "Request a new code")."""
    from app.platform.tenancy.models_cp import ActivationRequest

    cp_db = _cp()
    try:
        req = _open_request(cp_db, tenant.tenant_id)
        if req is None:
            last = (cp_db.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant.tenant_id)
                    .order_by(ActivationRequest.created_at.desc()).first())
            req = last if last is not None and last.status == "expired" else None
        return request_info(req)
    finally:
        cp_db.close()


# ---------------------------------------------------------------- company side

def request_activation(db, tenant, modules: list[str], user, *, with_needs: bool = False) -> dict:
    from app.audit.service import log_action
    from app.platform import module_status
    from app.platform.tenancy.models_cp import ActivationRequest

    wanted = set(modules)
    unknown = sorted(wanted - set(reg.CHOOSABLE))
    if unknown:
        raise ActivationError(f"Unknown module: {', '.join(unknown)}.", "UNKNOWN_MODULE")
    active = module_status.active_modules(db, tenant)
    missing = reg.missing_needs(wanted | active)
    missing = {k: v for k, v in missing.items() if k in wanted}
    if missing and not with_needs:
        need = sorted({n for v in missing.values() for n in v})
        raise ActivationError(f"Also switch on {_names(need)}? " + "; ".join(f"{reg.BY_KEY[k].name} needs {_names(v)}" for k, v in missing.items()) + ".",
                              "MODULE_NEEDS", 409, needs=need)
    if with_needs:
        wanted = reg.with_needs(wanted)
    actor = getattr(user, "email", "system")
    cp_db = _cp()
    try:
        previous = _open_request(cp_db, tenant.tenant_id)
        keys = sorted((wanted | set(previous.modules if previous is not None else [])) - active)
        if not keys:
            raise ActivationError("These modules are already active.", "ALREADY_ACTIVE", 409)
        replaced = None
        if previous is not None:
            previous.status, replaced = "replaced", previous.number
            _event(cp_db, previous, "replaced", by=f"client {actor}", status="done")
            _forget_code(cp_db, previous)
        company, where = _company(db, tenant)
        code = new_code()
        req = ActivationRequest(tenant_id=tenant.tenant_id, modules=keys, code_hash=_hash(code, tenant.tenant_id, keys), status="pending",
                                company_name=company, domain=where, requested_by_name=getattr(user, "full_name", None), requested_by_email=actor,
                                expires_at=_now() + timedelta(days=max(1, settings.ACTIVATION_CODE_DAYS)), created_at=_now(),
                                number=_next_number(cp_db), delivery="sending")
        cp_db.add(req)
        cp_db.flush()
        _keep_code(cp_db, req, code)
        del code  # only the hash and the encrypted copy remain
        _deliver(cp_db, req, "request", f"client {actor}")
        module_status.mark_pending(db, tenant, keys, actor)
        db.commit()
        cp_db.commit()
        info = request_info(req)
    finally:
        cp_db.close()
    log_action(db, "company_module", None, "activation_requested", actor[:50],
               {"modules": keys, "request": info["number"], "email_sent": info["email_sent"], "replaced": replaced})
    return info


def resend_request(db, tenant, user) -> dict:
    """[Resend request] / [Try sending again]: to the current priority approver; cooldown + daily limit."""
    from app.audit.service import log_action

    actor = getattr(user, "email", "system")
    cooldown = _int_setting("activation.resend_cooldown_minutes")
    per_day = _int_setting("activation.resend_max_per_day")
    cp_db = _cp()
    try:
        req = _open_request(cp_db, tenant.tenant_id)
        if req is None:
            raise ActivationError("There is no request waiting.", "NO_REQUEST", 404)
        now = _now()
        if req.expires_at < now:
            raise ActivationError("This code has expired - request a new one.", "CODE_EXPIRED")
        if req.last_resend_at and now < req.last_resend_at + timedelta(minutes=cooldown):
            wait = int((req.last_resend_at + timedelta(minutes=cooldown) - now).total_seconds() // 60) + 1
            raise ActivationError(f"You can resend in {wait} min.", "RESEND_COOLDOWN", 429, minutes=wait)
        if req.resend_day != now.date():
            req.resend_day, req.resends_today = now.date(), 0
        if req.resends_today >= per_day:
            raise ActivationError(f"You can resend at most {per_day} times a day. Please call CTD Techs and quote {req.number}.", "RESEND_LIMIT", 429)
        req.resends_today += 1
        req.resend_count = (req.resend_count or 0) + 1
        req.last_resend_at = now
        req.retry_count = 0
        ok = _deliver(cp_db, req, "resend", f"client {actor}")
        cp_db.commit()
        info = request_info(req)
    finally:
        cp_db.close()
    log_action(db, "company_module", None, "activation_resent", actor[:50], {"request": info["number"], "sent": ok})
    return info


def cancel_request(db, tenant, user) -> dict:
    """[Cancel request]: the waiting modules go back to Off."""
    from app.audit.service import log_action
    from app.platform import module_status

    actor = getattr(user, "email", "system")
    cp_db = _cp()
    try:
        req = _open_request(cp_db, tenant.tenant_id)
        if req is None:
            raise ActivationError("There is no request waiting.", "NO_REQUEST", 404)
        number, keys = req.number, list(req.modules or [])
        req.status = "cancelled"
        _event(cp_db, req, "cancelled", by=f"client {actor}", status="done")
        _forget_code(cp_db, req)
        _modules_back_off(db, tenant, keys)
        db.commit()
        cp_db.commit()
    finally:
        cp_db.close()
    module_status.invalidate(tenant.tenant_id)
    log_action(db, "company_module", None, "activation_request_cancelled", actor[:50], {"request": number, "modules": keys})
    return {"cancelled": number}


def _modules_back_off(db, tenant, keys) -> None:
    from app.models.company_module import CompanyModule

    for row in db.query(CompanyModule).filter(CompanyModule.tenant_id == tenant.tenant_id, CompanyModule.module_key.in_(keys),
                                              CompanyModule.status == "pending").all():
        row.status, row.updated_at = "off", _now()


def _lock_mail(cp_db, req) -> None:
    try:
        to = [a["email"] for a in _targets(req)]
        platform_mail.send(to, f"Activation code locked - {req.number} - {req.company_name}",
                           f"{req.company_name} ({req.domain}) entered a wrong activation code {MAX_TRIES} times.\n"
                           f"Request: {req.number}\nModules requested: {_names(req.modules)}\nRequested by: {req.requested_by_email}\n"
                           f"Code entry is locked until {_fmt(req.locked_until)}.\n")
        _event(cp_db, req, "lock_alert", to=to, by="system", status="sent")
    except (platform_mail.MailError, ActivationError) as exc:
        log.warning("activation lock email for %s not sent: %s", req.number, exc)
        _event(cp_db, req, "lock_alert", by="system", status="failed", reason=str(exc))


def activate_with_code(db, tenant, code: str, user) -> dict:
    from app.audit.service import log_action
    from app.platform import module_status
    from app.platform.tenancy.models_cp import ActivationRequest

    actor = getattr(user, "email", "system")
    now = _now()
    clean = normalise(code)
    cp_db = _cp()
    try:
        current = _open_request(cp_db, tenant.tenant_id)
        if current is not None and current.locked_until and current.locked_until > now:
            minutes = max(1, int((current.locked_until - now).total_seconds() // 60) + 1)
            raise ActivationError(f"Too many wrong tries. Please wait {minutes} minutes and try again.", "TOO_MANY_TRIES", 429)
        match = None
        if len(clean) == CODE_LENGTH and all(c in ALPHABET for c in clean):
            recent = (cp_db.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant.tenant_id)
                      .order_by(ActivationRequest.created_at.desc()).limit(10).all())
            match = next((r for r in recent if _matches(clean, r)), None)
        if match is None:
            if current is None:
                raise ActivationError("This code is not correct.", "WRONG_CODE")
            current.attempts = (current.attempts or 0) + 1
            left = MAX_TRIES - current.attempts
            if left <= 0:
                current.locked_until, current.attempts = now + timedelta(minutes=LOCK_MINUTES), 0
                _lock_mail(cp_db, current)
                request_id = str(current.id)
                cp_db.commit()
                log_action(db, "company_module", None, "activation_code_locked", actor[:50], {"request_id": request_id})
                raise ActivationError(f"This code is not correct. Too many wrong tries - code entry is locked for {LOCK_MINUTES} minutes and CTD Techs has been told.",
                                      "TOO_MANY_TRIES", 429)
            cp_db.commit()
            log_action(db, "company_module", None, "activation_code_wrong", actor[:50], {"tries_left": left})
            raise ActivationError(f"This code is not correct. {left} {'tries' if left != 1 else 'try'} left.", "WRONG_CODE", tries_left=left)
        if match.status == "activated":
            raise ActivationError("This code has already been used.", "CODE_USED")
        if match.status in ("cancelled", "replaced"):
            raise ActivationError("This code is no longer valid - a newer request replaced it. Use the latest code from CTD Techs.", "CODE_REPLACED")
        if match.status == "expired" or match.expires_at < now:
            match.status = "expired"
            cp_db.commit()
            raise ActivationError("This code has expired - request a new one.", "CODE_EXPIRED")
        # only modules still waiting: one switched off after the request needs a new code
        waiting = {m["key"] for m in module_status.status(db, tenant) if m["status"] == "pending"}
        keys = [k for k in (match.modules or []) if k in waiting]
        if not keys:
            raise ActivationError("None of the modules in this request are waiting any more. Request activation again.", "NOTHING_WAITING", 409)
        module_status.activate(db, tenant, keys, actor)
        match.status, match.activated_at, match.activated_by = "activated", now, actor
        _event(cp_db, match, "activated", by=f"client {actor}", status="done")
        _forget_code(cp_db, match)
        number = match.number  # read before the session closes
        db.commit()
        cp_db.commit()
    finally:
        cp_db.close()
    log_action(db, "company_module", None, "modules_activated", actor[:50], {"modules": keys, "request": number})
    return {"activated": keys, "names": _names(keys)}


# ---------------------------------------------------------------- background: retries + escalation

def sweep() -> dict:
    """Every minute (in-app scheduler; Celery beat in production). Retries failed sends with
    backoff and escalates requests nobody actioned. One process at a time (advisory lock)."""
    from sqlalchemy import text

    from app.platform.tenancy.models_cp import ActivationRequest

    done = {"retried": 0, "escalated": 0, "not_actioned": 0}
    cp_db = _cp()
    try:
        if not cp_db.execute(text("select pg_try_advisory_xact_lock(19021902)")).scalar():
            return {"skipped": "another process is sweeping"}
        now = _now()
        pending = cp_db.query(ActivationRequest).filter(ActivationRequest.status == "pending", ActivationRequest.expires_at > now).all()
        escalate_after = timedelta(minutes=_int_setting("activation.escalation_minutes"))
        send_all = bool(platform_mail.get_setting("activation.send_all"))
        for req in pending:
            if req.delivery in ("retrying", "sending") and req.next_retry_at and req.next_retry_at <= now:
                req.retry_count = (req.retry_count or 0) + 1
                _deliver(cp_db, req, "retry", "system")
                done["retried"] += 1
            elif req.delivery == "sent" and not send_all and req.last_sent_at and now - req.last_sent_at >= escalate_after:
                people = active_approvers()
                prev = next((a for a in people if a["priority"] == req.current_priority), None)
                later = [a for a in people if a["priority"] > (req.current_priority or 0)]
                if not later:
                    req.delivery = "not_actioned"
                    _event(cp_db, req, "escalation", by="system", status="failed", reason="Nobody left to escalate to (no further active priority).")
                    done["not_actioned"] += 1
                    continue
                note = f"Escalation: not actioned by {prev['email'] if prev else 'the previous approver'} since {_fmt(req.last_sent_at)}."
                _deliver(cp_db, req, "escalation", "system", priority=later[0]["priority"], note=note)
                req.current_priority = later[0]["priority"]
                done["escalated"] += 1
        cp_db.commit()
    except Exception:  # noqa: BLE001 -- a background sweep must never crash the scheduler
        log.exception("activation sweep failed")
        cp_db.rollback()
    finally:
        cp_db.close()
    return done


# ---------------------------------------------------------------- CTD Techs console

def list_requests(status: Optional[str] = None, limit: int = 200) -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationRequest, Tenant

    cp_db = _cp()
    try:
        rows = (cp_db.query(ActivationRequest, Tenant.slug).join(Tenant, Tenant.id == ActivationRequest.tenant_id)
                .order_by(ActivationRequest.created_at.desc()).limit(limit).all())
        out = []
        for req, slug in rows:
            info = request_info(req)
            if status and info["status"] != status:
                continue
            red = req.status == "pending" and req.delivery in ("failed", "not_actioned", "retrying")
            out.append({**info, "tenant": slug, "company": req.company_name, "installation": req.domain, "module_names": _names(req.modules),
                        "requested_by_name": req.requested_by_name, "emailed_to": list(req.emailed_to or []), "email_error": req.email_error,
                        "delivery_raw": req.delivery, "current_priority": req.current_priority, "retry_count": req.retry_count,
                        "next_retry_at": req.next_retry_at.isoformat() if req.next_retry_at else None, "attention": red,
                        "has_code": bool(req.code_ref), "activated_at": req.activated_at.isoformat() if req.activated_at else None,
                        "activated_by": req.activated_by})
        out.sort(key=lambda r: (not r["attention"],))  # red ones on top, newest first otherwise
        return out
    finally:
        cp_db.close()


def history(request_id) -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationEvent

    cp_db = _cp()
    try:
        return [{"at": e.at.isoformat() if e.at else None, "kind": e.kind, "sent_to": list(e.sent_to or []), "by": e.by, "status": e.status, "reason": e.reason}
                for e in cp_db.query(ActivationEvent).filter(ActivationEvent.request_id == request_id).order_by(ActivationEvent.at).all()]
    finally:
        cp_db.close()


def _console_request(cp_db, request_id):
    from app.platform.tenancy.models_cp import ActivationRequest

    req = cp_db.get(ActivationRequest, request_id)
    if req is None:
        raise ActivationError("No such activation request.", "NOT_FOUND", 404)
    return req


def console_resend(request_id, admin_email: str, *, priority: Optional[int] = None, everyone: bool = False) -> dict:
    """[Resend to priority 1/2/3] / [Resend to all] -- the SAME code."""
    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status != "pending":
            raise ActivationError(f"This request is {req.status}; there is nothing to resend.", "NOT_PENDING", 409)
        ok = _deliver(cp_db, req, "resend", f"ctd {admin_email}", priority=priority, everyone=everyone)
        _audit(cp_db, admin_email, "activation_resent", req.tenant_id, request=req.number, priority=priority, everyone=everyone, sent=ok)
        cp_db.commit()
        return {"sent": ok, "email_error": None if ok else req.email_error, "number": req.number}
    finally:
        cp_db.close()


def console_new_code(request_id, admin_email: str) -> dict:
    """[Generate new code]: the old code stops working; the new one is emailed to the current priority."""
    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status not in ("pending", "expired"):
            raise ActivationError(f"This request is {req.status}.", "NOT_PENDING", 409)
        code = new_code()
        req.code_hash, req.status, req.attempts, req.locked_until = _hash(code, req.tenant_id, req.modules or []), "pending", 0, None
        req.expires_at = _now() + timedelta(days=max(1, settings.ACTIVATION_CODE_DAYS))
        _keep_code(cp_db, req, code)
        _event(cp_db, req, "new_code", by=f"ctd {admin_email}", status="done")
        ok = _deliver(cp_db, req, "new_code", f"ctd {admin_email}", note="(New code -- the earlier code for this request no longer works.)")
        _audit(cp_db, admin_email, "activation_code_new", req.tenant_id, request=req.number, sent=ok)
        cp_db.commit()
        return {"sent": ok, "email_error": None if ok else req.email_error, "number": req.number}
    finally:
        cp_db.close()


def console_show_code(request_id, admin_email: str) -> dict:
    """[Show code] -- CTD super-admin only, audit-logged; for giving it by phone."""
    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status != "pending":
            raise ActivationError(f"This request is {req.status}.", "NOT_PENDING", 409)
        code = _kept_code(cp_db, req)
        if code is None:
            raise ActivationError("This request has no stored code (made before codes were kept). Use Generate new code.", "NO_CODE", 409)
        _event(cp_db, req, "code_shown", by=f"ctd {admin_email}", status="done")
        _audit(cp_db, admin_email, "activation_code_shown", req.tenant_id, request=req.number)
        cp_db.commit()
        return {"number": req.number, "code": pretty(code), "expires_at": req.expires_at.isoformat()}
    finally:
        cp_db.close()


def cancel(request_id, admin_email: str) -> dict:
    """The request stops; its modules that were waiting go back to off in the company."""
    from app.platform import module_status
    from app.platform.tenancy.context import tenant_context
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status != "pending":
            raise ActivationError(f"This request is already {req.status}.", "NOT_PENDING", 409)
        req.status = "cancelled"
        _event(cp_db, req, "cancelled", by=f"ctd {admin_email}", status="done")
        _forget_code(cp_db, req)
        tenant = cp_db.get(Tenant, req.tenant_id)
        with tenant_context(tenant.id, tenant.slug, tenant.isolation):
            from app.platform.tenancy.context import get_current_tenant

            db = tenant_session(tenant)
            try:
                _modules_back_off(db, get_current_tenant(), list(req.modules or []))
                db.commit()
                module_status.invalidate(tenant.id)
            finally:
                db.close()
        _audit(cp_db, admin_email, "activation_request_cancelled", req.tenant_id, request=req.number)
        cp_db.commit()
        return request_info(req)
    finally:
        cp_db.close()
