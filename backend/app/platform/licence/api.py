"""Part 32: the licence screens' API - where the company stands, the request for CTD, entering CTD's signed code, and
loading a new signed CTD file. Plus the lock: while a company waits for CTD's first approval only sign-in, the waiting
page and the code entry answer; after valid_until the modules are read-only."""

import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform.licence import codes
from app.platform.licence import config as ctd_config
from app.platform.licence import state as licence
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/licence", tags=["licence"])
ADMIN = "platform.settings.configure"


def _admin(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    from app.platform.iam.authz import has_permission

    if user.role != "admin" and not has_permission(db, require_current_tenant(), user, ADMIN):
        raise HTTPException(status_code=403, detail="Only an administrator can do this.")
    return user


def _error(exc) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status_code", 400), detail={"code": getattr(exc, "code", "LICENCE_ERROR"), "message": str(exc)})


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """What the waiting page / the banner / Settings > Licence show. The request text only for administrators."""
    from app.platform import activation
    from app.platform.iam.authz import has_permission

    tenant = require_current_tenant()
    s = licence.standing(tenant) if licence.enforced() else {"state": "approved", "modules": [], "valid_until": None, "expired": False,
                                                              "expiring_in_days": None, "grace_days_left": None}
    is_admin = user.role == "admin" or has_permission(db, tenant, user, ADMIN)
    request = activation.open_request(tenant) if is_admin else None
    return {**s, "set_up": ctd_config.load() is not None, "approver": ctd_config.approver_email(), "support": ctd_config.support(),
            "is_admin": is_admin, "request": request, "install_id": licence.install_id() if is_admin else None}


class AccessIn(BaseModel):
    modules: list[str] = Field(default_factory=list)


@router.post("/request-access")
def request_access(body: AccessIn, db: Session = Depends(get_db), user: User = Depends(_admin)):
    """A (new) first-access request - e.g. after the CTD file was loaded, or to ask again."""
    from app.platform import activation, module_status

    tenant = require_current_tenant()
    keys = body.modules or [m["key"] for m in module_status.status(db, tenant) if m["status"] in ("pending", "active")]
    try:
        return activation.request_access(db, tenant, keys, user)
    except activation.ActivationError as exc:
        raise _error(exc) from exc


class CodeIn(BaseModel):
    code: str = Field(min_length=10, max_length=20000)


@router.post("/code")
def enter_code(body: CodeIn, db: Session = Depends(get_db), user: User = Depends(_admin)):
    """CTD's signed approval code - first access or a module change (the same as Settings > Company > Modules)."""
    from app.platform import activation

    try:
        return activation.activate_with_code(db, require_current_tenant(), body.code, user)
    except activation.ActivationError as exc:
        raise _error(exc) from exc


@router.post("/config")
async def load_config(config: UploadFile = File(...), signature: Optional[UploadFile] = File(None), signature_text: Optional[str] = Form(None),
                      db: Session = Depends(get_db), user: User = Depends(_admin)):
    """Settings > Licence > "Load CTD file": ctd_config.json + its .sig from CTD Techs. Refused unless CTD signed it."""
    from app.audit.service import log_action

    data = await config.read()
    sig = (await signature.read()).decode(errors="replace") if signature is not None else (signature_text or "")
    try:
        loaded = ctd_config.install(data, sig)
    except codes.CodeError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    log_action(db, "licence", None, "ctd_file_loaded", user.email[:50], {"approver": loaded["approver_email"], "issued_at": loaded.get("issued_at")})
    return {"approver": loaded["approver_email"], "issued_at": loaded.get("issued_at")}


# ---------------------------------------------------------------- the lock

OPEN_WHILE_LOCKED = ("/auth/", "/api/v1/licence", "/api/me/bootstrap", "/api/me/", "/api/v1/me/", "/api/v1/public/branding", "/health",
                     "/healthz", "/readyz", "/metrics", "/api/v1/superadmin", "/api/v1/platform/signup", "/api/v1/i18n")
WAITING = {"detail": {"code": "WAITING_FOR_CTD", "message": "This installation is waiting for CTD Techs' approval. An administrator can enter "
                                                            "the approval code on the waiting page.", "fix_path": "/waiting-for-ctd"}}
EXPIRED = {"detail": {"code": "LICENCE_EXPIRED", "message": "The licence ended - you can still look at your data, but nothing new can be "
                                                            "done. Ask CTD Techs for a new approval code.", "fix_path": "/settings/advanced/licence"}}
_locked_cache: dict = {}


def _locked(tenant) -> tuple[bool, bool]:
    key = str(tenant.tenant_id)
    hit = _locked_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = (licence.locked(tenant), licence.read_only(tenant))
    _locked_cache[key] = (time.monotonic() + 5, value)
    return value


def clear_cache() -> None:
    _locked_cache.clear()


class LicenceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not licence.enforced():
            return await call_next(request)
        from app.platform.tenancy.context import get_current_tenant

        tenant = get_current_tenant()
        if tenant is None:
            return await call_next(request)
        path = request.url.path
        root = request.scope.get("root_path") or ""
        if root and path.startswith(root):
            path = path[len(root):] or "/"
        if request.method == "OPTIONS" or path.startswith(OPEN_WHILE_LOCKED):
            return await call_next(request)
        is_locked, is_read_only = _locked(tenant)
        if is_locked:
            return JSONResponse(status_code=403, content=WAITING)
        if is_read_only and request.method not in ("GET", "HEAD"):
            from app.platform import module_registry as reg

            if reg.module_for_api(path, request.method) is not None:
                return JSONResponse(status_code=403, content=EXPIRED)
        return await call_next(request)
