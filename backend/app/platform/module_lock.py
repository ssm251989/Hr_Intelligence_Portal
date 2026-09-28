"""Part 18.4: module unlock passcode.

Every main area of the app (LOCKABLE below, plus every other switched-on module from the
module registry) is LOCKED until an admin enters the module passcode once -- on Settings >
Modules or on the locked page itself. Unlocked stays unlocked until an admin locks it again.

- The passcode lives only as a bcrypt hash in `module_access` (never in code or git). It is set
  with `python -m hrctl.modules set-passcode --tenant <slug>` (prompted) and changed in
  Settings > Modules with the current passcode.
- Until a passcode has been set, locking is inactive (nothing can be unlocked without one, so
  locking then would shut everyone out).
- Settings `modules.lock.*`: on/off, one passcode for all (default) or one per module,
  5 wrong tries then a 15-minute wait. Every unlock / lock / wrong try / change is audited.
- ModuleLockMiddleware answers 403 {"detail": {"code": "MODULE_LOCKED", ...}} for the APIs of a
  locked area. A few read endpoints that every page needs (the applications list, one
  candidate, the jobs list) stay open so unlocking one area never breaks another.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

ALL = "__all__"
APP = r"/applications/[^/]+/"

# key -> (page paths in the app, API rules). An API rule is a regex on the path, optionally
# limited to write methods with a leading "W:" (shared lists stay readable).
LOCKABLE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "jobs": (("/jobs",), (r"^/api/v1/ui/jobs", r"^/api/v1/recruitment/(requisitions|jobs|pipeline-templates|knockout)", r"^/reports/(jobs|job-status)",
                          r"W:^/jobs")),
    "candidates": (("/candidates",), (r"^/candidates/(upload|applications)", r"^/local-import", r"^/api/v1/ui/candidates(?!/applications/[^/]+/evidence)",
                                      r"^/reports/candidates-", r"W:^/candidates")),
    "screening": (("/screening",), (r"^/screening", APP + r"(screen|rank)", r"^/api/v1/ui/screening", r"^/reports/screening-")),
    "shortlisting": (("/shortlisting",), (r"^/shortlisting", APP + r"shortlist-", r"^/reports/shortlisting-")),
    "interviews": (("/interviews",), (r"^/interviews", APP + r"(interviews|interview-questions)", r"^/interview-scheduling", r"^/api/v1/ui/interviews",
                                      r"^/api/v1/ui/interviewers", r"^/api/v1/recruitment/interviewer-availability", r"^/reports/interviews-")),
    "candidate_emails": (("/hr-inbox", "/candidate-emails"), (r"^/hr-inbox", r"^/api/v1/ui/hr-inbox", r"^/api/v1/ui/candidate-emails")),
    "salary": (("/salary",), (APP + r"(validate-salary|salary|approve-salary)", r"^/api/v1/ui/salary", r"^/api/v1/ui/stage-table/salary")),
    "bgv": (("/bgv",), (APP + r"bgv", r"^/api/v1/ui/stage-table/bgv")),
    "offers": (("/offers",), (APP + r"offer", r"^/api/v1/ui/offers", r"^/api/v1/recruitment/(offers|offer-components)", r"^/api/v1/ui/stage-table/offers")),
    "reports": (("/reports",), (r"^/reports/(pipeline|audit)", r"^/api/v1/intelligence/reports")),
    "settings": (("/settings",), (r"^/api/v1/settings", r"^/api/v1/connections", r"^/api/v1/connection-routes", r"^/api/v1/connectors",
                                  r"^/api/v1/comms", r"^/api/v1/iam", r"^/api/v1/scoring", r"^/api/v1/secrets", r"W:^/api/v1/media",
                                  r"W:^/api/v1/setup", r"W:^/api/v1/branding")),
    "genai_usage": (("/genai-usage",), (r"^/api/v1/ui/genai",)),
}
# never locked: signing in, the menu, the lock API itself, candidate-facing public pages
EXEMPT = re.compile(r"^/(auth|health|healthz|readyz|metrics|docs|redoc|openapi\.json)|^/api/me/|^/api/v1/modules/access|^/api/v1/public/|^/public/"
                    r"|^/interview-(confirm|negotiation)/")
WRITE = {"POST", "PUT", "PATCH", "DELETE"}
_COMPILED = {k: [(r.startswith("W:"), re.compile(r[2:] if r.startswith("W:") else r)) for r in rules] for k, (_p, rules) in LOCKABLE.items()}


def _other_modules() -> dict[str, tuple[str, ...]]:
    from app.platform.modules import MODULES

    return {m.code: m.api_prefixes for m in MODULES if not m.always_on and m.api_prefixes and m.code not in LOCKABLE}


def lock_key_for_api(path: str, method: str) -> Optional[str]:
    if EXEMPT.search(path):
        return None
    for key, rules in _COMPILED.items():
        for write_only, rx in rules:
            if rx.search(path) and (not write_only or method in WRITE):
                return key
    for code, prefixes in _other_modules().items():
        if any(path.startswith(p) for p in prefixes):
            return code
    return None


def lock_key_for_page(path: str) -> Optional[str]:
    """Which lockable area an app page (menu path) belongs to."""
    from app.platform.modules import MODULES

    for key, (pages, _rules) in LOCKABLE.items():
        if any(path == p or path.startswith(p + "/") for p in pages):
            return key
    for m in MODULES:
        if not m.always_on and m.code not in LOCKABLE and any(path == n.path or path.startswith(n.path + "/") for n in m.nav):
            return m.code
    return None


def lockable_keys(db, tenant) -> list[str]:
    from app.platform.modules import enabled_modules

    on = enabled_modules(db, tenant)
    return list(LOCKABLE) + [code for code in _other_modules() if code in on]


# ---------------------------------------------------------------- state

def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _rows(db, tenant) -> dict:
    from app.models.module_access import ModuleAccess

    return {r.module_key: r for r in db.query(ModuleAccess).filter(ModuleAccess.tenant_id == tenant.tenant_id).all()}


def _mode(db, tenant) -> str:
    return "per_module" if _setting(db, tenant, "modules.lock.mode") == "per_module" else "one"


def is_active(db, tenant, rows: Optional[dict] = None) -> bool:
    """Locking works only when switched on AND a passcode has been set."""
    if not _setting(db, tenant, "modules.lock.enabled"):
        return False
    rows = _rows(db, tenant) if rows is None else rows
    return any(r.passcode_hash for r in rows.values())


def locked_keys(db, tenant) -> set[str]:
    rows = _rows(db, tenant)
    if not is_active(db, tenant, rows):
        return set()
    return {k for k in lockable_keys(db, tenant) if not (rows.get(k) and rows[k].unlocked_at)}


def status(db, tenant) -> dict:
    rows = _rows(db, tenant)
    active = is_active(db, tenant, rows)
    mode = _mode(db, tenant)
    now = datetime.now(timezone.utc)
    items = []
    for key in lockable_keys(db, tenant):
        r = rows.get(key)
        items.append({"module": key, "locked": active and not (r and r.unlocked_at),
                      "unlocked_at": r.unlocked_at.isoformat() if r and r.unlocked_at else None, "unlocked_by": r.unlocked_by if r else None,
                      "has_own_passcode": bool(r and r.passcode_hash)})
    guard = rows.get(ALL)
    wait = guard.lockout_until if guard and guard.lockout_until and guard.lockout_until > now else None
    return {"enabled": bool(_setting(db, tenant, "modules.lock.enabled")), "active": active, "mode": mode,
            "passcode_set": bool(guard and guard.passcode_hash) if mode == "one" else any(r.passcode_hash for r in rows.values()),
            "try_again_at": wait.isoformat() if wait else None, "modules": items}


# ---------------------------------------------------------------- passcode

class LockError(ValueError):
    def __init__(self, message: str, code: str = "BAD_PASSCODE", status_code: int = 400):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def _row(db, tenant, key: str):
    from app.models.module_access import ModuleAccess

    row = db.query(ModuleAccess).filter(ModuleAccess.tenant_id == tenant.tenant_id, ModuleAccess.module_key == key).first()
    if row is None:
        row = ModuleAccess(tenant_id=tenant.tenant_id, module_key=key)
        db.add(row)
        db.flush()
    return row


def _check_passcode(db, tenant, key: str, passcode: str, actor: str) -> None:
    """Checks against the one passcode (or this module's own in per-module mode). Wrong tries
    are counted on the "__all__" row so the limit applies to the company, not per module."""
    from app.audit.service import log_action
    from app.core.security import verify_password

    now = datetime.now(timezone.utc)
    guard = _row(db, tenant, ALL)
    if guard.lockout_until and guard.lockout_until > now:
        minutes = max(1, int((guard.lockout_until - now).total_seconds() // 60) + 1)
        raise LockError(f"Too many wrong tries. Please wait {minutes} minute{'s' if minutes != 1 else ''} and try again.", "TOO_MANY_TRIES", 429)
    source = _row(db, tenant, key) if _mode(db, tenant) == "per_module" and key != ALL else guard
    hashed = source.passcode_hash or guard.passcode_hash
    if not hashed:
        raise LockError("No passcode has been set yet. The owner sets it once with: hrctl modules set-passcode --tenant <company>.", "NO_PASSCODE", 409)
    if not verify_password(passcode or "", hashed):
        guard.failed_attempts = (guard.failed_attempts or 0) + 1
        limit = int(_setting(db, tenant, "modules.lock.max_attempts") or 5)
        left = limit - guard.failed_attempts
        if left <= 0:
            guard.lockout_until = now + timedelta(minutes=int(_setting(db, tenant, "modules.lock.lockout_minutes") or 15))
            guard.failed_attempts = 0
        db.commit()
        log_action(db, "module_access", None, "module_passcode_wrong", actor[:50], {"module": key, "tries_left": max(left, 0)})
        if left <= 0:
            raise LockError(f"Too many wrong tries. Please wait {int(_setting(db, tenant, 'modules.lock.lockout_minutes') or 15)} minutes and try again.", "TOO_MANY_TRIES", 429)
        raise LockError(f"That passcode isn't right. {left} {'tries' if left != 1 else 'try'} left.")
    guard.failed_attempts, guard.lockout_until = 0, None


def unlock(db, tenant, key: str, passcode: str, actor: str) -> dict:
    from app.audit.service import log_action

    keys = lockable_keys(db, tenant)
    if key != ALL and key not in keys:
        raise LockError("Unknown module.", "UNKNOWN_MODULE", 404)
    _check_passcode(db, tenant, key, passcode, actor)
    now = datetime.now(timezone.utc)
    targets = keys if key == ALL else [key]
    for k in targets:
        row = _row(db, tenant, k)
        row.unlocked_at, row.unlocked_by, row.updated_at = now, actor[:200], now
    db.commit()
    invalidate(tenant.tenant_id)
    log_action(db, "module_access", None, "module_unlocked", actor[:50], {"modules": targets})
    return status(db, tenant)


def lock(db, tenant, key: str, actor: str) -> dict:
    from app.audit.service import log_action

    keys = lockable_keys(db, tenant)
    targets = keys if key == ALL else [key]
    for k in targets:
        row = _row(db, tenant, k)
        row.unlocked_at = row.unlocked_by = None
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    invalidate(tenant.tenant_id)
    log_action(db, "module_access", None, "module_locked", actor[:50], {"modules": targets})
    return status(db, tenant)


def set_passcode(db, tenant, new: str, actor: str, *, key: str = ALL, current: Optional[str] = None, require_current: bool = True) -> None:
    """The CLI sets it without the current one (it runs on the server); the app needs it."""
    from app.audit.service import log_action
    from app.core.security import hash_password

    if len(new or "") < 6:
        raise LockError("The passcode needs at least 6 characters.", "WEAK_PASSCODE")
    if require_current:
        _check_passcode(db, tenant, key, current or "", actor)
    row = _row(db, tenant, key)
    first_time = not any(r.passcode_hash for r in _rows(db, tenant).values())
    row.passcode_hash = hash_password(new)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    invalidate(tenant.tenant_id)
    log_action(db, "module_access", None, "module_passcode_set" if first_time else "module_passcode_changed", actor[:50], {"module": key})


# ---------------------------------------------------------------- middleware (5-second cache)

_CACHE: dict = {}


def invalidate(tenant_id) -> None:
    _CACHE.pop(str(tenant_id), None)


def _cached_locked(tenant) -> set[str]:
    hit = _CACHE.get(str(tenant.tenant_id))
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        keys = locked_keys(db, tenant)
    finally:
        db.close()
    _CACHE[str(tenant.tenant_id)] = (time.monotonic() + 5, keys)
    return keys


LOCKED_MESSAGE = "This module is locked. An admin needs to enter the module passcode to unlock it (Settings > Modules, or on the page itself)."


class ModuleLockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = lock_key_for_api(request.url.path, request.method)
        if key is not None:
            from app.platform.tenancy.context import get_current_tenant

            tenant = get_current_tenant()
            if tenant is not None and key in _cached_locked(tenant):
                return JSONResponse(status_code=403, content={"detail": {"code": "MODULE_LOCKED", "message": LOCKED_MESSAGE, "module": key,
                                                                          "fix_path": "/settings/advanced/modules"}})
        return await call_next(request)
