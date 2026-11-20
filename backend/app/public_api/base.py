"""Part 30.2b: the public API's frame -- /api/public/v1 as its own FastAPI app (own OpenAPI at /api/public/v1/docs,
only public endpoints), one error shape {"error": {"code", "message"}}, the key check, a per-key rate limit and a
usage row per call (per-call pricing).

The main app's middlewares still run first: the company is resolved from the host (TenantResolver), so a key is
looked up only in that company's own database; Idempotency-Key on a POST replays the first answer.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.public_api import ApiKey
from app.models.user import User
from app.platform.tenancy.context import get_current_tenant

API_PREFIX = "/api/public/v1"
# scope -> the module it uses (the same activation rule as the screens; cards follow their own permissions)
SCOPE_MODULE = {"jobs": "jobs", "candidates": "candidates", "screening": "screening", "scheduling": "interviews"}
CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid", 429: "rate_limited"}


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, headers: Optional[dict] = None):
        super().__init__(status_code=status, detail={"code": code, "message": message}, headers=headers)


def error_body(status: int, detail) -> dict:
    if isinstance(detail, dict) and "message" in detail:
        return {"error": {"code": detail.get("code") or CODES.get(status, "error"), "message": str(detail["message"])}}
    return {"error": {"code": CODES.get(status, "error"), "message": str(detail)}}


class Caller:
    """Who is calling: the key and the person it acts as (their permissions apply)."""

    def __init__(self, key: ApiKey, user: User, tenant):
        self.key, self.user, self.tenant = key, user, tenant


def _rate_limit(db: Session, tenant, key: ApiKey) -> None:
    from app.platform.ops.rate_limit import _hit
    from app.platform.settings.resolver import SettingContext, SettingsService

    limit = int(SettingsService(db).get("platform.api.rate_limit_per_minute", SettingContext(tenant=tenant)) or 60)
    window = int(time.time() // 60)
    if _hit(f"t:{tenant.tenant_id}:rl:apikey:{key.id}:{window}", window) > limit:
        retry = 60 - int(time.time() % 60)
        raise ApiError(429, "rate_limited", f"This key may make {limit} calls a minute. Try again in {retry} s.", headers={"Retry-After": str(retry)})


def caller(scope: str):
    """Dependency: a valid key for this company with `scope`."""

    def _dep(request: Request, db: Session = Depends(get_db)) -> Caller:
        from app.public_api.keys import KeyError_, authenticate

        tenant = get_current_tenant()
        auth = request.headers.get("authorization") or ""
        raw = auth[7:] if auth.lower().startswith("bearer ") else ""
        try:
            key, user = authenticate(db, tenant, raw)
        except KeyError_ as exc:
            raise ApiError(exc.status, exc.code, exc.message, headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None) from exc
        request.state.api_key_id = key.id
        _rate_limit(db, tenant, key)
        if scope not in (key.scopes or []):
            raise ApiError(403, "missing_scope", f"This key does not have the '{scope}' scope. Add it to a new key on Settings > Developers.")
        module = SCOPE_MODULE.get(scope)
        if module:  # proof 30.2h: the API created a job for a company whose Jobs module CTD had not activated
            from app.platform import module_status

            if not module_status.is_active(db, tenant, module):
                raise ApiError(403, "module_not_active", f"The {module.replace('_', ' ')} module is not active for your company yet "
                                                         "(Settings > Company > Modules; CTD activates it).")
        from app.platform.ai.tracked import set_actor

        set_actor(user.id)  # AI usage is counted for the key's owner, as on the screens
        return Caller(key, user, tenant)

    return _dep


def need_permission(c: Caller, db: Session, permission: str) -> None:
    from app.platform.iam.authz import has_permission

    if not has_permission(db, c.tenant, c.user, permission):
        raise ApiError(403, "forbidden", f"The person who created this key does not have '{permission}', so the key cannot do this either.")


USAGE_SESSION = None  # tests: a callable returning their own session (the default opens and closes one)


def _record_usage(request: Request, status: int, ms: int) -> None:
    key_id = getattr(request.state, "api_key_id", None)
    tenant = get_current_tenant()
    if key_id is None or tenant is None:
        return  # no valid key: nothing to bill
    from app.core.database import SessionLocal
    from app.models.public_api import ApiUsage

    route = request.scope.get("route")
    endpoint = (getattr(route, "path", None) or request.url.path)[:200]
    own = USAGE_SESSION is None
    db = SessionLocal() if own else USAGE_SESSION()
    try:
        db.add(ApiUsage(tenant_id=tenant.tenant_id, api_key_id=key_id, method=request.method, endpoint=endpoint, status_code=status, ms=ms,
                        created_at=datetime.now(timezone.utc)))
        db.commit()
    except Exception:  # noqa: BLE001 -- metering never breaks a call
        db.rollback()
    finally:
        if own:
            db.close()


def _unexpected(exc: Exception) -> JSONResponse:
    """Anything a handler did not turn into an ApiError: still the API's error shape, never a bare 500 page."""
    import logging

    from app.platform.connectors.router import NoConnectionForPurposeError

    if isinstance(exc, NoConnectionForPurposeError):
        return JSONResponse(status_code=503, content={"error": {"code": "ai_unavailable", "message": str(exc)}})
    logging.getLogger(__name__).exception("public API: unexpected error")
    return JSONResponse(status_code=500, content={"error": {"code": "server_error", "message": "Something went wrong on our side. "
                                                                                                  "Retry later; send the same Idempotency-Key on a POST."}})


def build_app(routers: list) -> FastAPI:
    api = FastAPI(title="HR Automation public API", version="1.0.0", docs_url="/docs", redoc_url=None, openapi_url="/openapi.json",
                  description="Call the HR agents from your own systems. Authenticate with `Authorization: Bearer <key>` "
                              "(Settings > Developers). Errors are `{\"error\": {\"code\", \"message\"}}`. Send `Idempotency-Key` "
                              "on a POST to make a retry safe. Full guide: docs/PUBLIC_API.md.")

    @api.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.status_code, exc.detail), headers=getattr(exc, "headers", None))

    @api.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body",))
        return JSONResponse(status_code=422, content={"error": {"code": "invalid", "message": f"{where}: {first.get('msg', 'invalid value')}".strip(": ")}})

    @api.middleware("http")
    async def _meter(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 -- proof 30.2h: an unexpected error came back as plain text
            response = _unexpected(exc)
        _record_usage(request, response.status_code, int((time.perf_counter() - start) * 1000))
        return response

    for r in routers:
        api.include_router(r)
    return api
