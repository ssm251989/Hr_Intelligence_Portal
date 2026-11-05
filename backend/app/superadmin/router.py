"""Super-Admin console API (docs/HRMS_COMPLETE_SPEC.txt Part 13 section B): tenants, plans,
modules, usage, health, impersonation. A separate route tree with its own identities
(`platform_admins` in the control plane -- never a tenant user) and MANDATORY TOTP: an
admin with no enrolled TOTP secret cannot sign in at all (enrol with `hrctl superadmin
create`). Every action is written to `superadmin_audit`; impersonation is additionally
written to the TENANT's own audit_log so the client can see who accessed their account.
Runs with no TenantContext (see TenantResolverMiddleware's TENANTLESS_PATH_PREFIXES).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, verify_password
from app.platform.secrets.store import get_secret_store
from app.platform.tenancy import provisioning
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import (
    ControlPlaneSecret,
    ControlPlaneSecretScope,
    ImpersonationSession,
    Plan,
    PlatformAdmin,
    SuperAdminAudit,
    Tenant,
    TenantDomain,
    TenantModule,
)

router = APIRouter(prefix="/api/v1/superadmin", tags=["superadmin"])
_SCOPE = "superadmin"


def _cp():
    db = ControlPlaneSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _audit(cp_db, admin_email: str, action: str, tenant_id=None, **details) -> None:
    cp_db.add(SuperAdminAudit(admin_email=admin_email, action=action, tenant_id=tenant_id, details_json=details))
    cp_db.commit()


def current_admin(authorization: str = Header(default=""), cp_db=Depends(_cp)) -> PlatformAdmin:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to the console")
    try:
        claims = decode_access_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired -- sign in again")
    if claims.get("scope") != _SCOPE:
        raise HTTPException(status_code=403, detail="Not a console session")
    admin = cp_db.get(PlatformAdmin, UUID(claims["sub"]))
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=403, detail="Console access revoked")
    return admin


# ---- auth ----


class ConsoleLogin(BaseModel):
    email: str
    password: str
    totp_code: str


@router.post("/login")
def login(payload: ConsoleLogin, cp_db=Depends(_cp)):
    admin = cp_db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email.lower()).first()
    generic = HTTPException(status_code=401, detail="Email, password or code is incorrect")
    if admin is None or not admin.is_active or not admin.password_hash or not verify_password(payload.password, admin.password_hash):
        raise generic
    if not admin.mfa_secret_ref:
        raise HTTPException(status_code=403, detail="Two-factor authentication is mandatory for the console -- enrol with hrctl superadmin create")
    secret = get_secret_store(cp_db, ControlPlaneSecret, ControlPlaneSecretScope, provisioning.CONTROL_PLANE_SECRET_SCOPE).get(admin.mfa_secret_ref)
    if not pyotp.TOTP(secret).verify(payload.totp_code, valid_window=1):
        _audit(cp_db, admin.email, "login_failed_mfa")
        raise generic
    admin.last_login_at = datetime.now(timezone.utc)
    cp_db.commit()
    _audit(cp_db, admin.email, "login")
    token = create_access_token(str(admin.id), extra_claims={"scope": _SCOPE, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.SUPERADMIN_SESSION_MINUTES)})
    return {"access_token": token, "expires_in_minutes": settings.SUPERADMIN_SESSION_MINUTES}


# ---- tenants ----


def _tenant_or_404(cp_db, slug: str) -> Tenant:
    tenant = cp_db.query(Tenant).filter(Tenant.slug == slug).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _tenant_dict(cp_db, t: Tenant) -> dict:
    plan = cp_db.get(Plan, t.plan_id) if t.plan_id else None
    return {"id": str(t.id), "slug": t.slug, "name": t.display_name, "status": t.status, "isolation": t.isolation, "region": t.region,
            "plan": plan.code if plan else None, "created_at": t.created_at.isoformat() if t.created_at else None,
            "domains": [d.host for d in cp_db.query(TenantDomain).filter(TenantDomain.tenant_id == t.id).all()],
            "modules": {m.module_code: m.enabled for m in cp_db.query(TenantModule).filter(TenantModule.tenant_id == t.id).all()}}


@router.get("/tenants")
def list_tenants(admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    return [_tenant_dict(cp_db, t) for t in cp_db.query(Tenant).order_by(Tenant.created_at.asc()).all()]


class TenantCreate(BaseModel):
    slug: str
    name: str
    isolation: str = "dedicated_db"
    region: str = "ap-south-1"
    plan_code: Optional[str] = None
    admin_email: Optional[str] = None
    domain: Optional[str] = None
    dry_run: bool = True  # the console always shows the plan first


@router.post("/tenants")
def create_tenant(payload: TenantCreate, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    try:
        result = provisioning.create_tenant(notify=lambda _m: None, **payload.model_dump())
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(cp_db, admin.email, "tenant_create_dry_run" if payload.dry_run else "tenant_create", details_slug=payload.slug)
    return result


class StatusChange(BaseModel):
    status: str
    reason: Optional[str] = None


@router.post("/tenants/{slug}/status")
def change_status(slug: str, payload: StatusChange, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    tenant = _tenant_or_404(cp_db, slug)
    try:
        result = provisioning.set_status(slug, payload.status, reason=payload.reason)
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(cp_db, admin.email, "tenant_status", tenant.id, status=payload.status, reason=payload.reason)
    return result


class ModuleToggle(BaseModel):
    enabled: bool
    limits: dict = {}


@router.put("/tenants/{slug}/modules/{module_code}")
def toggle_module(slug: str, module_code: str, payload: ModuleToggle, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    tenant = _tenant_or_404(cp_db, slug)
    row = cp_db.query(TenantModule).filter(TenantModule.tenant_id == tenant.id, TenantModule.module_code == module_code).first()
    if row is None:
        row = TenantModule(tenant_id=tenant.id, module_code=module_code)
        cp_db.add(row)
    row.enabled, row.limits_json = payload.enabled, payload.limits
    cp_db.commit()
    _audit(cp_db, admin.email, "module_toggle", tenant.id, module=module_code, enabled=payload.enabled)
    return {"module": module_code, "enabled": row.enabled}


@router.get("/plans")
def list_plans(admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    return [{"code": p.code, "name": p.name, "modules": p.module_codes, "limits": p.limits_json} for p in cp_db.query(Plan).order_by(Plan.code).all()]


class PlanUpsert(BaseModel):
    code: str
    name: str
    module_codes: list[str] = []
    limits: dict = {}


@router.put("/plans")
def upsert_plan(payload: PlanUpsert, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    plan = cp_db.query(Plan).filter(Plan.code == payload.code).first()
    if plan is None:
        plan = Plan(code=payload.code, name=payload.name)
        cp_db.add(plan)
    plan.name, plan.module_codes, plan.limits_json = payload.name, payload.module_codes, payload.limits
    cp_db.commit()
    _audit(cp_db, admin.email, "plan_upsert", code=payload.code)
    return {"code": plan.code}


@router.get("/tenants/{slug}/usage")
def tenant_usage(slug: str, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    from sqlalchemy import create_engine

    tenant = _tenant_or_404(cp_db, slug)
    engine = create_engine(provisioning.admin_dsn_for(cp_db, tenant))
    counts = {}
    with engine.connect() as conn:
        for table in ("users", "employees", "candidates", "applications", "tickets", "copilot_messages"):
            counts[table] = conn.execute(sa_text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'), {"t": str(tenant.id)}).scalar()
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ai = conn.execute(sa_text("SELECT coalesce(sum(input_tokens + output_tokens), 0), coalesce(sum(cost), 0) FROM ai_usage_records WHERE tenant_id = :t AND created_at >= :m"),
                          {"t": str(tenant.id), "m": month_start}).one()
    engine.dispose()
    _audit(cp_db, admin.email, "tenant_usage_view", tenant.id)
    return {"slug": slug, "rows": counts, "ai_this_month": {"tokens": int(ai[0]), "cost": float(ai[1])}}


@router.get("/tenants/{slug}/health")
def tenant_health(slug: str, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    """DB reachability + each connection's last test result (per-tenant connection health)."""
    from sqlalchemy import create_engine

    tenant = _tenant_or_404(cp_db, slug)
    out = {"database": {"ok": False}}
    try:
        engine = create_engine(provisioning.admin_dsn_for(cp_db, tenant))
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
            rows = conn.execute(sa_text("SELECT name, provider_code, status, last_tested_at, last_test_result FROM connections WHERE tenant_id = :t"), {"t": str(tenant.id)}).mappings().all()
        engine.dispose()
        out["database"] = {"ok": True}
        out["connections"] = [{"name": r["name"], "provider": r["provider_code"], "status": r["status"],
                               "last_tested_at": r["last_tested_at"].isoformat() if r["last_tested_at"] else None,
                               "ok": bool((r["last_test_result"] or {}).get("success"))} for r in rows]
    except Exception as exc:
        out["database"] = {"ok": False, "error": type(exc).__name__}
    return out


# ---- impersonation (audited, time-boxed, tenant-visible) ----


class ImpersonateRequest(BaseModel):
    user_email: str
    reason: str
    minutes: int = 15


@router.post("/tenants/{slug}/impersonate")
def impersonate(slug: str, payload: ImpersonateRequest, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    if len(payload.reason.strip()) < 10:
        raise HTTPException(status_code=400, detail="Give a real reason (it is shown to the client)")
    minutes = max(1, min(payload.minutes, settings.IMPERSONATION_MAX_MINUTES))
    tenant = _tenant_or_404(cp_db, slug)
    if tenant.status != "active":
        raise HTTPException(status_code=409, detail="Only an active tenant can be accessed")

    from app.audit.service import log_action
    from app.models.user import User
    from app.platform.tenancy.context import tenant_context

    with tenant_context(tenant.id):
        tdb = provisioning.tenant_session(tenant)
        try:
            user = tdb.query(User).filter(User.email == payload.user_email.lower()).first()
            if user is None:
                raise HTTPException(status_code=404, detail="No such user in this tenant")
            session = ImpersonationSession(platform_admin_id=admin.id, tenant_id=tenant.id, target_user_id=user.id, reason=payload.reason,
                                           expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes))
            cp_db.add(session)
            cp_db.commit()
            log_action(tdb, "user", user.id, "platform_impersonation_started", f"platform:{admin.email}"[:50],
                       {"reason": payload.reason, "minutes": minutes, "session_id": str(session.id)})
            user_id = user.id
        finally:
            tdb.close()
    _audit(cp_db, admin.email, "impersonation_started", tenant.id, user=payload.user_email, minutes=minutes, session_id=str(session.id))
    token = create_access_token(str(user_id), extra_claims={"tid": str(tenant.id), "imp": str(session.id), "imp_by": admin.email,
                                                            "exp": session.expires_at})
    return {"access_token": token, "expires_at": session.expires_at.isoformat(), "session_id": str(session.id)}


@router.post("/impersonations/{session_id}/end")
def end_impersonation(session_id: UUID, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    session = cp_db.get(ImpersonationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.ended_at = datetime.now(timezone.utc)
    cp_db.commit()
    _audit(cp_db, admin.email, "impersonation_ended", session.tenant_id, session_id=str(session_id))
    return {"ended_at": session.ended_at.isoformat()}


@router.get("/audit")
def console_audit(limit: int = 200, admin: PlatformAdmin = Depends(current_admin), cp_db=Depends(_cp)):
    rows = cp_db.query(SuperAdminAudit).order_by(SuperAdminAudit.created_at.desc()).limit(min(limit, 1000)).all()
    return [{"at": r.created_at.isoformat() if r.created_at else None, "admin": r.admin_email, "action": r.action,
             "tenant_id": str(r.tenant_id) if r.tenant_id else None, "details": r.details_json} for r in rows]


# ---- Part 19.2 / 19.2b / 19.2c: activation requests, approvers, platform mailbox (all installations) ----


def _act_error(exc) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/activation-requests")
def activation_requests(status: Optional[str] = None, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation, platform_mail

    return {"requests": activation.list_requests(status), "approvers": activation.list_approvers(), "mailbox": platform_mail.health(),
            "settings": platform_mail.all_settings()}


@router.get("/activation-requests/{request_id}/history")
def activation_history(request_id: UUID, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    return activation.history(request_id)


class ResendIn(BaseModel):
    priority: Optional[int] = None
    all: bool = False


@router.post("/activation-requests/{request_id}/resend")
def activation_resend(request_id: UUID, body: ResendIn, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.console_resend(request_id, admin.email, priority=body.priority, everyone=body.all)
    except activation.ActivationError as exc:
        raise _act_error(exc)


@router.post("/activation-requests/{request_id}/new-code")
def activation_new_code(request_id: UUID, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.console_new_code(request_id, admin.email)
    except activation.ActivationError as exc:
        raise _act_error(exc)


@router.post("/activation-requests/{request_id}/show-code")
def activation_show_code(request_id: UUID, admin: PlatformAdmin = Depends(current_admin)):
    """CTD super-admin only; audit-logged (superadmin_audit + request history)."""
    from app.platform import activation

    try:
        return activation.console_show_code(request_id, admin.email)
    except activation.ActivationError as exc:
        raise _act_error(exc)


@router.post("/activation-requests/{request_id}/cancel")
def activation_cancel(request_id: UUID, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.cancel(request_id, admin.email)
    except activation.ActivationError as exc:
        raise _act_error(exc)


class ApproverIn(BaseModel):
    email: str
    name: Optional[str] = None
    active: bool = True


@router.put("/activation-approvers/{priority}")
def approver_set(priority: int, body: ApproverIn, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.set_approver(priority, body.email, admin.email, name=body.name, active=body.active)
    except activation.ActivationError as exc:
        raise _act_error(exc)


@router.delete("/activation-approvers/{priority}")
def approver_remove(priority: int, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.remove_approver(priority, admin.email)
    except activation.ActivationError as exc:
        raise _act_error(exc)


class ReorderIn(BaseModel):
    emails: list[str]


@router.post("/activation-approvers/reorder")
def approver_reorder(body: ReorderIn, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import activation

    try:
        return activation.reorder_approvers(body.emails, admin.email)
    except activation.ActivationError as exc:
        raise _act_error(exc)


class MailboxIn(BaseModel):
    host: str
    port: int = 587
    user: str = ""
    starttls: bool = True
    from_name: str = "CTD Techs HRMS"
    from_address: str
    password: Optional[str] = None  # None = keep the stored one


@router.put("/platform-mailbox")
def mailbox_set(body: MailboxIn, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import platform_mail

    try:
        platform_mail.set_mailbox(host=body.host, port=body.port, user=body.user, starttls=body.starttls, from_name=body.from_name,
                                  from_address=body.from_address, password=body.password, actor=admin.email)
    except platform_mail.MailError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_MAILBOX", "message": exc.reason})
    return platform_mail.health()


class MailTestIn(BaseModel):
    to: str


@router.post("/platform-mailbox/test")
def mailbox_test(body: MailTestIn, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import platform_mail

    return platform_mail.test(body.to, admin.email)


@router.put("/platform-settings")
def platform_settings_set(body: dict, admin: PlatformAdmin = Depends(current_admin)):
    from app.platform import platform_mail

    try:
        for key, value in body.items():
            platform_mail.set_setting(key, value, admin.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_SETTING", "message": str(exc)})
    return platform_mail.all_settings()
