"""Part 28.5: cloud sign-up - "Create your company" on the PLATFORM domain (docs/INSTALLER.md, PART28 28.5).

    start()      the form: rules from install/validate.py (the only place with input rules), a captcha, a rate
                 limit; the admin password is kept ONLY as a bcrypt hash; a confirmation link (30 min, single use)
                 is emailed through the platform mailbox.
    confirm()    the link: the company is created in the background (provision()) and the page shows progress.
    provision()  provisioning.create_tenant (its own database) + the first admin with the CHOSEN password (the hash)
                 + <slug>.<PLATFORM_DOMAIN> + activation.request_activation (modules wait for CTD Techs' approval).
    welcome()    called when CTD Techs' activation code switches the modules on: "your company is ready" email.

Nothing here decides for a person: CTD Techs still approves every company's modules.
"""

import hashlib
import hmac
import logging
import random
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.platform.install.validate import InvalidInput, check_signup
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import SignupRequest, Tenant, TenantDomain

log = logging.getLogger(__name__)
LINK_MINUTES = 30
CAPTCHA_MINUTES = 10
SAME_ANSWER = {"ok": True, "message": "Check your email: we sent a link to confirm and create your company. It works once, for 30 minutes."}


class SignupError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- captcha (no third party: a signed sum)


def new_captcha() -> dict:
    a, b = random.randint(2, 9), random.randint(2, 9)
    expires = int(time.time()) + CAPTCHA_MINUTES * 60
    payload = f"{a + b}:{expires}"
    sig = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return {"question": f"What is {a} + {b}?", "token": f"{expires}.{sig}"}


def captcha_ok(token: str, answer: str) -> bool:
    try:
        expires, sig = (token or "").split(".", 1)
        if int(expires) < time.time():
            return False
        want = hmac.new(settings.SECRET_KEY.encode(), f"{int(str(answer).strip())}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(want, sig)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- start / confirm


def host_for(slug: str) -> str:
    return f"{slug}.{settings.PLATFORM_DOMAIN}".lower()


def slug_free(slug: str) -> bool:
    cp = ControlPlaneSessionLocal()
    try:
        taken = cp.query(Tenant.id).filter(Tenant.slug == slug).first() or cp.query(TenantDomain.id).filter(TenantDomain.host == host_for(slug)).first()
        pending = cp.query(SignupRequest.id).filter(SignupRequest.slug == slug, SignupRequest.status.in_(("confirmed", "provisioning", "waiting_approval", "active"))).first()
        return not (taken or pending)
    finally:
        cp.close()


def start(*, company_name: str, company_slug: str, admin_name: str, admin_email: str, password: str, password2: str, modules: list[str],
          captcha_token: str, captcha_answer: str, ip: Optional[str]) -> dict:
    from app.core.security import hash_password
    from app.platform.ops.rate_limit import _hit

    window = int(time.time() // 3600)
    if _hit(f"signup:ip:{ip}:{window}", window) > 5 or _hit(f"signup:email:{(admin_email or '').lower()}:{window}", window) > 3:
        raise SignupError("Too many sign-ups from here. Try again in an hour.", 429)
    problems: dict = {}
    try:
        check_signup(company_name=company_name, company_slug=company_slug, admin_name=admin_name, admin_email=admin_email,
                     password=password, password2=password2)
    except InvalidInput as exc:
        problems.update(exc.problems)
    if not captcha_ok(captcha_token, captcha_answer):
        problems["captcha"] = "The answer to the question is not right (or it expired). Try the new question."
    slug = (company_slug or "").strip().lower()
    if "company_slug" not in problems and not slug_free(slug):
        problems["company_slug"] = "That short name is taken. Choose another."
    from app.platform import module_registry as reg

    bad = [m for m in modules or [] if m not in reg.CHOOSABLE]
    if bad:
        problems["modules"] = f"Unknown module: {', '.join(bad)}."
    if problems:
        raise InvalidInput(problems)
    token = secrets.token_urlsafe(32)
    cp = ControlPlaneSessionLocal()
    try:
        row = SignupRequest(company_name=company_name.strip(), slug=slug, admin_name=admin_name.strip(), admin_email=admin_email.strip().lower(),
                            password_hash=hash_password(password), modules=sorted(set(modules or [])), token_hash=_sha(token),
                            token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=LINK_MINUTES), ip=(ip or "")[:64])
        cp.add(row)
        cp.commit()
        link = f"{settings.PLATFORM_URL.rstrip('/')}/signup/confirm?token={token}"
    finally:
        cp.close()
    _mail([admin_email.strip()], f"Confirm your company {company_name.strip()} on HR Automation",
          f"Hi {admin_name.strip()},\n\nConfirm your email to create {company_name.strip()} on HR Automation "
          f"({host_for(slug)}). The link works once, for {LINK_MINUTES} minutes:\n{link}\n\n"
          "If you didn't sign up, ignore this email - nothing is created.\nCTD Techs")
    return {**SAME_ANSWER, "link_for_tests": link if settings.ENV != "production" and _testing() else None}


def _testing() -> bool:
    import sys

    return "pytest" in sys.modules


def confirm(token: str, *, background: bool = True) -> dict:
    cp = ControlPlaneSessionLocal()
    try:
        row = cp.query(SignupRequest).filter(SignupRequest.token_hash == _sha(token or "")).first()
        if row is None:
            raise SignupError("This link isn't valid. Sign up again.", 404)
        if row.status != "pending_email":
            return status_of(row)  # already confirmed: the page just shows the progress
        if row.token_expires_at < datetime.now(timezone.utc):
            row.status = "expired"
            cp.commit()
            raise SignupError("This link has expired (it works for 30 minutes). Sign up again.", 410)
        if not slug_free(row.slug):
            row.status, row.error = "failed", "The short name was taken meanwhile."
            cp.commit()
            raise SignupError("That short name was taken meanwhile. Sign up again with another one.", 409)
        row.status, row.confirmed_at, row.updated_at = "confirmed", datetime.now(timezone.utc), datetime.now(timezone.utc)
        cp.commit()
        rid = row.id
        out = status_of(row)
    finally:
        cp.close()
    if background:
        threading.Thread(target=provision, args=(rid,), daemon=True).start()
    else:
        provision(rid)
    return out


def status_by_token(token: str) -> dict:
    cp = ControlPlaneSessionLocal()
    try:
        row = cp.query(SignupRequest).filter(SignupRequest.token_hash == _sha(token or "")).first()
        if row is None:
            raise SignupError("This link isn't valid.", 404)
        return status_of(row)
    finally:
        cp.close()


def status_of(row: SignupRequest) -> dict:
    return {"status": row.status, "company": row.company_name, "host": row.host or host_for(row.slug), "admin_email": row.admin_email,
            "modules": row.modules, "error": row.error if row.status == "failed" else None,
            "sign_in_url": f"http://{row.host}" + (":5173" if settings.PLATFORM_DOMAIN == "localhost" else "") + "/login" if row.host else None}


# ---------------------------------------------------------------- provision (background job)


def _set(rid, **fields) -> None:
    cp = ControlPlaneSessionLocal()
    try:
        row = cp.get(SignupRequest, rid)
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(timezone.utc)
        cp.commit()
    finally:
        cp.close()


def provision(rid) -> None:
    """create_tenant -> first admin with the chosen password (hash) -> domain -> activation request."""
    from app.platform.tenancy import provisioning

    cp = ControlPlaneSessionLocal()
    try:
        row = cp.get(SignupRequest, rid)
        slug, name, email, admin_name, pw_hash, modules = row.slug, row.company_name, row.admin_email, row.admin_name, row.password_hash, list(row.modules or [])
    finally:
        cp.close()
    _set(rid, status="provisioning")
    host = host_for(slug)
    try:
        result = provisioning.create_tenant(slug=slug, name=name, isolation="dedicated_db", domain=host, admin_email=None, notify=lambda m: None)
        tenant_id = result["tenant_id"]
        _set(rid, tenant_id=tenant_id, host=host)
        first_admin(tenant_id, slug, email=email, name=admin_name, password_hash=pw_hash, modules=modules)
        _set(rid, status="waiting_approval", error=None)
    except Exception as exc:  # noqa: BLE001 -- shown on the progress page + the super-admin list
        log.exception("sign-up %s failed", slug)
        _set(rid, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])


def first_admin(tenant_id, slug: str, *, email: str, name: str, password_hash: str, modules: list[str]) -> None:
    from app.models.user import User
    from app.platform import activation
    from app.platform.iam.roles import bridge_single_user
    from app.platform.tenancy import provisioning
    from app.platform.tenancy.context import TenantContext, tenant_context

    cp = ControlPlaneSessionLocal()
    try:
        tenant = cp.get(Tenant, tenant_id)
        cp.expunge(tenant)
    finally:
        cp.close()
    ctx = TenantContext(tenant_id=tenant.id, slug=slug, isolation=tenant.isolation)
    with tenant_context(tenant.id, slug=slug):
        db = provisioning.tenant_session(tenant)
        try:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(tenant_id=tenant.id, email=email, role="admin", full_name=name, hashed_password=password_hash)
                db.add(user)
            user.hashed_password, user.role, user.full_name = password_hash, "admin", name
            user.password_set_at = user.password_changed_at = datetime.now(timezone.utc)
            db.commit()
            bridge_single_user(db, ctx, user)
            if modules:
                try:
                    activation.request_activation(db, ctx, modules, user, with_needs=True)
                except activation.ActivationError as exc:  # e.g. already active -> nothing to ask
                    log.info("sign-up %s activation: %s", slug, exc)
        finally:
            bind = db.get_bind()
            db.close()
            bind.dispose()  # tenant_session makes its own engine: release its connections


# ---------------------------------------------------------------- welcome + mail


def welcome(tenant_id) -> bool:
    """CTD Techs approved (the activation code switched the modules on): tell the person who signed up."""
    cp = ControlPlaneSessionLocal()
    try:
        row = cp.query(SignupRequest).filter(SignupRequest.tenant_id == tenant_id, SignupRequest.status == "waiting_approval").first()
        if row is None:
            return False
        row.status, row.updated_at = "active", datetime.now(timezone.utc)
        cp.commit()
        info = status_of(row)
        to, company, admin_name = row.admin_email, row.company_name, row.admin_name
    finally:
        cp.close()
    _mail([to], f"{company} is ready on HR Automation",
          f"Hi {admin_name},\n\nCTD Techs switched on your modules - {company} is ready.\nSign in at {info['sign_in_url']} with {to} "
          "and the password you chose.\n\nCTD Techs")
    return True


def _mail(to: list[str], subject: str, body: str) -> None:
    from app.platform import platform_mail

    try:
        platform_mail.send(to, subject, body)
    except Exception:  # noqa: BLE001 -- the sign-up row is kept; CTD Techs sees it in the console
        log.exception("sign-up email failed: %s", subject)


def all_signups(limit: int = 200) -> list[dict]:
    cp = ControlPlaneSessionLocal()
    try:
        rows = cp.query(SignupRequest).order_by(SignupRequest.created_at.desc()).limit(limit).all()
        return [{"id": str(r.id), "company": r.company_name, "slug": r.slug, "host": r.host or host_for(r.slug), "admin_email": r.admin_email,
                 "admin_name": r.admin_name, "modules": r.modules, "status": r.status, "error": r.error, "ip": r.ip,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None, "tenant_id": str(r.tenant_id) if r.tenant_id else None}
                for r in rows]
    finally:
        cp.close()
