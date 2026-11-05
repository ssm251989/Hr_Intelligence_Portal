"""Part 19.1: which modules this company has (company_modules) and the gate that enforces it.

active_modules() is what everything else asks: the menu, Home, settings, Setup, background
jobs, email templates, the hiring stage order, and ModuleActivationMiddleware, which answers
403 "This module is not active for your company" for the APIs of a module that isn't active.
Switching ON goes through an activation code (app/platform/activation.py); switching OFF is
immediate.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.platform import module_registry as reg

FIX_PATH = "/settings/company/modules"


class ModuleError(ValueError):
    def __init__(self, message: str, code: str = "MODULE_ERROR", status_code: int = 400, **extra):
        super().__init__(message)
        self.code, self.status_code, self.extra = code, status_code, extra


def _rows(db, tenant) -> dict:
    from app.models.company_module import CompanyModule

    return {r.module_key: r for r in db.query(CompanyModule).filter(CompanyModule.tenant_id == tenant.tenant_id).all()}


def active_modules(db, tenant) -> set[str]:
    """Active modules, plus GenAI usage when any AI module is active."""
    return reg.with_included({k for k, r in _rows(db, tenant).items() if r.status == "active" and k in reg.BY_KEY})


def is_active(db, tenant, key: str) -> bool:
    return key in active_modules(db, tenant)


def status(db, tenant) -> list[dict]:
    """One entry per module of the registry: off / pending / active (+ who and when)."""
    rows = _rows(db, tenant)
    active = active_modules(db, tenant)
    out = []
    for m in reg.MODULES:
        r = rows.get(m.key)
        state = "active" if m.key in active else (r.status if r is not None and not m.included else "off")
        out.append({**next(c for c in reg.catalog() if c["key"] == m.key), "status": state,
                    "requested_at": r.requested_at.isoformat() if r is not None and r.requested_at else None,
                    "requested_by": r.requested_by if r is not None else None,
                    "activated_at": r.activated_at.isoformat() if r is not None and r.activated_at else None,
                    "activated_by": r.activated_by if r is not None else None})
    return out


def _row(db, tenant, key: str):
    from app.models.company_module import CompanyModule

    rows = _rows(db, tenant)
    if key in rows:
        return rows[key]
    row = CompanyModule(tenant_id=tenant.tenant_id, module_key=key, status="off")
    db.add(row)
    db.flush()
    return row


def _check_keys(keys) -> list[str]:
    keys = sorted(set(keys))
    unknown = [k for k in keys if k not in reg.CHOOSABLE]
    if unknown:
        raise ModuleError(f"Unknown module: {', '.join(unknown)}.", "UNKNOWN_MODULE", 400)
    return keys


def mark_pending(db, tenant, keys, actor: str) -> list[str]:
    """Requested modules wait for the activation code. Already-active ones are left alone."""
    now = datetime.now(timezone.utc)
    rows = _rows(db, tenant)
    waiting = [k for k in _check_keys(keys) if not (rows.get(k) and rows[k].status == "active")]
    for k in waiting:
        row = _row(db, tenant, k)
        row.status, row.requested_at, row.requested_by, row.updated_at = "pending", now, actor[:200], now
    db.flush()
    invalidate(tenant.tenant_id)
    return waiting


def activate(db, tenant, keys, actor: str) -> list[str]:
    now = datetime.now(timezone.utc)
    done = []
    for k in _check_keys(keys):
        row = _row(db, tenant, k)
        if row.status != "active":
            row.status, row.activated_at, row.activated_by, row.updated_at = "active", now, actor[:200], now
            done.append(k)
    db.flush()
    invalidate(tenant.tenant_id)
    return done


def switch_off(db, tenant, keys, actor: str, *, with_dependents: bool = False) -> list[str]:
    """No code needed. A module another active one needs is refused unless with_dependents,
    which switches those off too (the UI asks first)."""
    from app.audit.service import log_action

    keys = set(_check_keys(keys))
    on = {k for k, r in _rows(db, tenant).items() if r.status in ("active", "pending")}
    dependents = sorted({d for k in keys for d in reg.needed_by(k, on)} - keys)
    if dependents and not with_dependents:
        names = ", ".join(reg.BY_KEY[d].name for d in dependents)
        raise ModuleError(f"{names} {'needs' if len(dependents) == 1 else 'need'} this module. Switch {'it' if len(dependents) == 1 else 'them'} off too?",
                          "MODULE_NEEDED", 409, dependents=dependents)
    targets = sorted(keys | set(dependents))
    now = datetime.now(timezone.utc)
    for k in targets:
        row = _row(db, tenant, k)
        row.status, row.updated_at = "off", now
    db.commit()
    invalidate(tenant.tenant_id)
    log_action(db, "company_module", None, "modules_switched_off", actor[:50], {"modules": targets})
    return targets


# ---------------------------------------------------------------- gate (5-second cache)

_CACHE: dict = {}


def invalidate(tenant_id) -> None:
    _CACHE.pop(str(tenant_id), None)


def cached_active(tenant) -> set[str]:
    hit = _CACHE.get(str(tenant.tenant_id))
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        keys = active_modules(db, tenant)
    finally:
        db.close()
    _CACHE[str(tenant.tenant_id)] = (time.monotonic() + 5, keys)
    return keys


def not_active_body(key: Optional[str]) -> dict:
    return {"detail": {"code": "MODULE_NOT_ACTIVE", "message": reg.MODULE_NOT_ACTIVE, "module": key,
                       "module_name": reg.BY_KEY[key].name if key in reg.BY_KEY else None,
                       "fix": "An admin can switch it on in Settings > Company > Modules.", "fix_path": FIX_PATH}}


class ModuleActivationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = reg.module_for_api(request.url.path, request.method)
        if key is not None:
            from app.platform.tenancy.context import get_current_tenant

            tenant = get_current_tenant()
            if tenant is not None and key not in cached_active(tenant):
                return JSONResponse(status_code=403, content=not_active_body(key))
        return await call_next(request)
