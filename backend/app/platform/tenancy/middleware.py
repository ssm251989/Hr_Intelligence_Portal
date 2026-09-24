"""TenantResolverMiddleware (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2, resolution
order from section B):
  1. Custom domain / subdomain (Host header) -> control_plane.tenant_domains
  2. X-Tenant-Slug header (for API/mobile clients, only if enabled)
  3. In single mode: the only tenant.
Unknown host -> 404, suspended tenant -> 423. Sets TenantContext for the duration of the
request; every downstream dependency (get_db, get_current_user, ...) reads it via
get_current_tenant() rather than re-resolving anything.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.platform.tenancy.context import TenantContext, reset_current_tenant, set_current_tenant
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import Tenant, TenantDomain


def _to_context(tenant: Tenant) -> TenantContext:
    return TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)


# Process-local cache for TENANCY_MODE=single's "the only tenant" lookup -- there is
# exactly one tenant row for the lifetime of a single-tenant installation's process (no
# request ever creates/deletes/reassigns it), so re-querying the control plane on every
# single request buys nothing but latency. Caches the plain fields actually needed, not the
# ORM instance itself, to avoid any question of accessing a detached SQLAlchemy object after
# its owning session has closed. Cleared by clear_single_tenant_cache() for tests/tooling
# that mutate the control-plane tenant row mid-process. Multi mode's host/header resolution
# below deliberately has no cache -- correctness there depends on per-request routing,
# unlike single mode's one fixed answer.
_single_tenant_cache: tuple | None = None  # (status, suspended_reason, TenantContext) | None


def clear_single_tenant_cache() -> None:
    global _single_tenant_cache
    _single_tenant_cache = None


class TenantResolverMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _single_tenant_cache
        if settings.TENANCY_MODE == "single" and _single_tenant_cache is not None:
            status, suspended_reason, ctx = _single_tenant_cache
        else:
            db = ControlPlaneSessionLocal()
            try:
                tenant = self._resolve(request, db)
                status = tenant.status if tenant else None
                suspended_reason = tenant.suspended_reason if tenant else None
                ctx = _to_context(tenant) if tenant else None
            finally:
                db.close()
            if settings.TENANCY_MODE == "single" and tenant is not None:
                _single_tenant_cache = (status, suspended_reason, ctx)

        if ctx is None:
            return JSONResponse(status_code=404, content={"detail": "No tenant is configured for this host"})
        if status == "suspended":
            return JSONResponse(status_code=423, content={"detail": suspended_reason or "This tenant is suspended"})

        token = set_current_tenant(ctx)
        try:
            return await call_next(request)
        finally:
            reset_current_tenant(token)

    def _resolve(self, request: Request, db) -> Tenant | None:
        if settings.TENANCY_MODE == "single":
            # Exactly one tenant row ever exists under this mode (decision A1) -- host/
            # header resolution below is dormant code for TENANCY_MODE=multi, not
            # exercised by the one deployment shape actually shipped at launch.
            return db.query(Tenant).order_by(Tenant.created_at.asc()).first()

        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            domain = db.query(TenantDomain).filter(TenantDomain.host == host).first()
            if domain is not None:
                return db.get(Tenant, domain.tenant_id)

        slug_header = request.headers.get("x-tenant-slug")
        if slug_header:
            return db.query(Tenant).filter(Tenant.slug == slug_header).first()

        return None
