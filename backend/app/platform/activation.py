"""Part 19.2: switching modules on with an activation code sent to CTD Techs.

1. A company admin chooses modules and asks for activation -> the modules wait
   ("pending") and ONE code is made for this request.
2. Only a bcrypt hash of the code is kept (control plane, activation_requests), bound to this
   company + the exact module list; it expires (ACTIVATION_CODE_DAYS) and works once.
3. The code is emailed to the CTD Techs approvers -- never to the company -- through the
   PLATFORM mailbox (PLATFORM_SMTP_*), so the company can't read or redirect it.
4. The company enters the code it got from CTD Techs -> those modules become active.
   5 wrong tries -> locked for 30 minutes and CTD Techs is told.
Turning a module off needs no code; on again needs a new one. A new request replaces the open
one (same modules + the new ones); active modules stay active.

The approvers come from ACTIVATION_APPROVER_EMAILS (or `hrctl activation set-approver`, kept in
the control plane) and must all be in ACTIVATION_ALLOWED_DOMAIN, itself ctdtechs.com or under
it: the app refuses to start, and refuses to send, otherwise.
"""

import hashlib
import logging
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings
from app.platform import module_registry as reg

log = logging.getLogger(__name__)

OWNER_DOMAIN = "ctdtechs.com"  # the platform owner; approvers can never be outside it
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes: 0/O, 1/I
CODE_LENGTH = 8
MAX_TRIES = 5
LOCK_MINUTES = 30
APPROVERS_KEY = "activation.approver_emails"
_EMAIL = re.compile(r"^[^@\s]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


class ActivationError(ValueError):
    def __init__(self, message: str, code: str = "ACTIVATION_ERROR", status_code: int = 400, **extra):
        super().__init__(message)
        self.code, self.status_code, self.extra = code, status_code, extra


# ---------------------------------------------------------------- approvers (platform-level)

def _domain_allowed(domain: str) -> bool:
    domain = (domain or "").strip().lower()
    return domain == OWNER_DOMAIN or domain.endswith("." + OWNER_DOMAIN)


def validate_approvers(emails, allowed_domain: Optional[str] = None) -> list[str]:
    allowed = (allowed_domain or settings.ACTIVATION_ALLOWED_DOMAIN).strip().lower()
    if not _domain_allowed(allowed):
        raise ActivationError(f"ACTIVATION_ALLOWED_DOMAIN must be {OWNER_DOMAIN} (or under it), not {allowed!r}.", "APPROVER_NOT_ALLOWED")
    out = []
    for e in emails:
        e = (e or "").strip().lower()
        if not _EMAIL.match(e):
            raise ActivationError(f"{e!r} isn't an email address.", "APPROVER_NOT_ALLOWED")
        domain = e.rsplit("@", 1)[1]
        if domain != allowed and not domain.endswith("." + allowed):
            raise ActivationError(f"{e} is not a {allowed} address. Activation codes only go to {allowed}.", "APPROVER_NOT_ALLOWED")
        out.append(e)
    if not out:
        raise ActivationError("At least one approver email is needed.", "APPROVER_NOT_ALLOWED")
    return out


def check_startup() -> None:
    """Called when the app starts: refuse to run with an approver outside ctdtechs.com."""
    try:
        validate_approvers(settings.ACTIVATION_APPROVER_EMAILS)
    except ActivationError as exc:
        raise RuntimeError(f"Module activation is misconfigured: {exc}") from exc


def approvers() -> list[str]:
    """The control-plane list (hrctl activation set-approver) if set, else the env list; checked every time."""
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig

    cp_db = ControlPlaneSessionLocal()
    try:
        row = cp_db.get(PlatformConfig, APPROVERS_KEY)
        stored = list(row.value_json) if row is not None and isinstance(row.value_json, list) else None
    finally:
        cp_db.close()
    return validate_approvers(stored if stored else settings.ACTIVATION_APPROVER_EMAILS)


def set_approvers(emails: list[str], actor: str) -> list[str]:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig, SuperAdminAudit

    clean = validate_approvers(emails)
    cp_db = ControlPlaneSessionLocal()
    try:
        row = cp_db.get(PlatformConfig, APPROVERS_KEY)
        if row is None:
            row = PlatformConfig(key=APPROVERS_KEY, value_json=clean)
            cp_db.add(row)
        row.value_json, row.updated_by, row.updated_at = clean, actor, datetime.now(timezone.utc)
        cp_db.add(SuperAdminAudit(admin_email=actor[:255], action="activation_approvers_set", details_json={"approvers": clean}))
        cp_db.commit()
    finally:
        cp_db.close()
    return clean


# ---------------------------------------------------------------- platform mailbox

def send_platform_mail(to: list[str], subject: str, body: str) -> None:
    """The PLATFORM system mailbox -- never a company's own mail connection."""
    if not settings.PLATFORM_SMTP_HOST:
        raise ActivationError("The platform mailbox isn't set up (PLATFORM_SMTP_HOST).", "PLATFORM_MAIL_NOT_SET", 503)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.PLATFORM_MAIL_FROM, ", ".join(to), subject
    msg.set_content(body)
    with smtplib.SMTP(settings.PLATFORM_SMTP_HOST, settings.PLATFORM_SMTP_PORT, timeout=20) as smtp:
        if settings.PLATFORM_SMTP_STARTTLS:
            smtp.starttls()
        if settings.PLATFORM_SMTP_USER:
            smtp.login(settings.PLATFORM_SMTP_USER, settings.PLATFORM_SMTP_PASSWORD)
        smtp.send_message(msg)


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


# ---------------------------------------------------------------- helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cp():
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal

    return ControlPlaneSessionLocal()


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


def _email_code(req, code: str, *, resent: bool = False) -> None:
    """Sends the code to the approvers; records where it went or why it didn't."""
    try:
        to = approvers()
        subject = f"Activation request - {req.company_name} - {_names(req.modules)}"
        body = (
            f"{'(New code -- the earlier code for this request no longer works.)' + chr(10) + chr(10) if resent else ''}"
            f"Company: {req.company_name}\n"
            f"Installation: {req.domain}\n"
            f"Requested by: {req.requested_by_name or '-'} <{req.requested_by_email or '-'}>\n"
            f"Modules: {_names(req.modules)}\n"
            f"Requested at: {_fmt(req.created_at or _now())}\n\n"
            f"Activation code: {pretty(code)}\n"
            f"Valid until: {_fmt(req.expires_at)} (works once)\n\n"
            "Share this code with the company when they may use these modules. They enter it on\n"
            "Settings > Company > Modules.\n"
        )
        send_platform_mail(to, subject, body)
        req.emailed_at, req.emailed_to, req.email_error = _now(), to, None
    except Exception as exc:  # noqa: BLE001 -- the request stays; CTD Techs can resend from the console
        log.warning("activation email for request %s not sent: %s", req.id, exc)
        req.email_error = str(exc)[:500]


def _open_request(cp_db, tenant_id):
    from app.platform.tenancy.models_cp import ActivationRequest

    return (cp_db.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant_id, ActivationRequest.status == "pending")
            .order_by(ActivationRequest.created_at.desc()).first())


def request_info(req) -> Optional[dict]:
    if req is None:
        return None
    now = _now()
    return {"id": str(req.id), "modules": list(req.modules or []), "status": "expired" if req.status == "pending" and req.expires_at < now else req.status,
            "requested_at": req.created_at.isoformat() if req.created_at else None, "requested_by": req.requested_by_email,
            "expires_at": req.expires_at.isoformat(), "email_sent": req.emailed_at is not None,
            "locked_until": req.locked_until.isoformat() if req.locked_until and req.locked_until > now else None,
            "tries_left": MAX_TRIES - (req.attempts or 0)}


def open_request(tenant) -> Optional[dict]:
    cp_db = _cp()
    try:
        return request_info(_open_request(cp_db, tenant.tenant_id))
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
        if previous is not None:
            previous.status = "replaced"
        company, where = _company(db, tenant)
        code = new_code()
        req = ActivationRequest(tenant_id=tenant.tenant_id, modules=keys, code_hash=_hash(code, tenant.tenant_id, keys), status="pending",
                                company_name=company, domain=where, requested_by_name=getattr(user, "full_name", None), requested_by_email=actor,
                                expires_at=_now() + timedelta(days=max(1, settings.ACTIVATION_CODE_DAYS)), created_at=_now())
        cp_db.add(req)
        cp_db.flush()
        _email_code(req, code)
        del code  # never kept, never logged
        module_status.mark_pending(db, tenant, keys, actor)
        db.commit()
        cp_db.commit()
        info = request_info(req)
    finally:
        cp_db.close()
    log_action(db, "company_module", None, "activation_requested", actor[:50],
               {"modules": keys, "request_id": info["id"], "email_sent": info["email_sent"], "replaced": str(previous.id) if previous is not None else None})
    return info


def _lock_mail(req) -> None:
    try:
        send_platform_mail(approvers(), f"Activation code locked - {req.company_name}",
                           f"{req.company_name} ({req.domain}) entered a wrong activation code {MAX_TRIES} times.\n"
                           f"Modules requested: {_names(req.modules)}\nRequested by: {req.requested_by_email}\n"
                           f"Code entry is locked until {_fmt(req.locked_until)}.\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("activation lock email not sent: %s", exc)


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
                cp_db.commit()
                _lock_mail(current)
                log_action(db, "company_module", None, "activation_code_locked", actor[:50], {"request_id": str(current.id)})
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
        db.commit()
        cp_db.commit()
    finally:
        cp_db.close()
    log_action(db, "company_module", None, "modules_activated", actor[:50], {"modules": keys, "request_id": str(match.id)})
    return {"activated": keys, "names": _names(keys)}


# ---------------------------------------------------------------- CTD Techs console

def list_requests(status: Optional[str] = None, limit: int = 200) -> list[dict]:
    from app.platform.tenancy.models_cp import ActivationRequest, Tenant

    cp_db = _cp()
    try:
        q = cp_db.query(ActivationRequest, Tenant.slug).join(Tenant, Tenant.id == ActivationRequest.tenant_id)
        rows = q.order_by(ActivationRequest.created_at.desc()).limit(limit).all()
        out = []
        for req, slug in rows:
            info = request_info(req)
            if status and info["status"] != status:
                continue
            out.append({**info, "tenant": slug, "company": req.company_name, "installation": req.domain, "module_names": _names(req.modules),
                        "requested_by_name": req.requested_by_name, "emailed_to": list(req.emailed_to or []), "email_error": req.email_error,
                        "activated_at": req.activated_at.isoformat() if req.activated_at else None, "activated_by": req.activated_by})
        return out
    finally:
        cp_db.close()


def _console_request(cp_db, request_id):
    from app.platform.tenancy.models_cp import ActivationRequest

    req = cp_db.get(ActivationRequest, request_id)
    if req is None:
        raise ActivationError("No such activation request.", "NOT_FOUND", 404)
    return req


def renew_code(request_id, admin_email: str, *, show: bool) -> dict:
    """Resend email / generate a new code: only the hash is kept, so both make a NEW code (the
    old one stops working) and email it; `show` also returns it once to the console."""
    from app.platform.tenancy.models_cp import SuperAdminAudit

    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status not in ("pending", "expired"):
            raise ActivationError(f"This request is {req.status}; there is nothing to resend.", "NOT_PENDING", 409)
        code = new_code()
        req.code_hash, req.status, req.attempts, req.locked_until = _hash(code, req.tenant_id, req.modules or []), "pending", 0, None
        req.expires_at = _now() + timedelta(days=max(1, settings.ACTIVATION_CODE_DAYS))
        _email_code(req, code, resent=True)
        cp_db.add(SuperAdminAudit(admin_email=admin_email[:255], action="activation_code_new" if show else "activation_email_resent",
                                  tenant_id=req.tenant_id, details_json={"request_id": str(req.id), "email_sent": req.email_error is None}))
        cp_db.commit()
        out = {**request_info(req), "email_error": req.email_error}
        if show:
            out["code"] = pretty(code)
        return out
    finally:
        cp_db.close()


def cancel(request_id, admin_email: str) -> dict:
    """The request stops; its modules that were waiting go back to off in the company."""
    from app.platform import module_status
    from app.platform.tenancy.context import tenant_context
    from app.platform.tenancy.models_cp import SuperAdminAudit, Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp_db = _cp()
    try:
        req = _console_request(cp_db, request_id)
        if req.status != "pending":
            raise ActivationError(f"This request is already {req.status}.", "NOT_PENDING", 409)
        req.status = "cancelled"
        tenant = cp_db.get(Tenant, req.tenant_id)
        with tenant_context(tenant.id, tenant.slug, tenant.isolation):
            from app.models.company_module import CompanyModule
            from app.platform.tenancy.context import get_current_tenant

            db = tenant_session(tenant)
            try:
                for row in db.query(CompanyModule).filter(CompanyModule.tenant_id == tenant.id, CompanyModule.module_key.in_(list(req.modules or [])),
                                                          CompanyModule.status == "pending").all():
                    row.status, row.updated_at = "off", _now()
                db.commit()
                module_status.invalidate(get_current_tenant().tenant_id)
            finally:
                db.close()
        cp_db.add(SuperAdminAudit(admin_email=admin_email[:255], action="activation_request_cancelled", tenant_id=req.tenant_id,
                                  details_json={"request_id": str(req.id)}))
        cp_db.commit()
        return request_info(req)
    finally:
        cp_db.close()
