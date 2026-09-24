"""TenantContext (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2) -- a contextvar so every
layer (request handling, DB session setup, Celery tasks) can read "which tenant is this"
without threading a parameter through every function call. Set once per request by
TenantResolverMiddleware (or once per task by platform.jobs.TenantTask); read everywhere
else via get_current_tenant().
"""

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

# Well-known id for "tenant #1" (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 3 + Part 1
# assumption 5: this installation's pre-existing single-tenant data becomes tenant #1). A
# literal, not
# gen_random_uuid()'d, specifically so the tenant migration's backfill, hrctl tenant
# bootstrap-existing, and every test's default TenantContext can all agree on the same id
# without a control-plane round trip -- this is the ONE tenant id ever allowed to be a
# literal in code, since under TENANCY_MODE=single (section B, the only mode deployed at
# launch) every installation has exactly one tenant and its slug/display_name (the actual
# per-client values) still come from CLI args / control-plane data, never from here.
TENANT_1_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    slug: str
    isolation: str
    locale: str = "en-IN"
    tz: str = "Asia/Kolkata"


_current_tenant: "contextvars.ContextVar[Optional[TenantContext]]" = contextvars.ContextVar(
    "current_tenant", default=None
)


def get_current_tenant() -> Optional[TenantContext]:
    return _current_tenant.get()


def set_current_tenant(ctx: Optional[TenantContext]) -> contextvars.Token:
    """Returns a Token -- pass it to reset_current_tenant() to restore whatever was set
    before (or nothing, at the top of a request/task), rather than blindly clearing it."""
    return _current_tenant.set(ctx)


def reset_current_tenant(token: contextvars.Token) -> None:
    _current_tenant.reset(token)


@contextmanager
def tenant_context(tenant_id: UUID, slug: str = "", isolation: str = "dedicated_db"):
    """For code with no request to inherit a TenantContext from -- today, this app's one
    APScheduler background job (app/local_import/scheduler.py, service.py), which always
    runs in the single tenant under TENANCY_MODE=single. Celery's own TenantTask base
    (Part 13) replaces this for real per-tenant fan-out once TENANCY_MODE=multi is
    actually deployed; this is the interim, explicit, single-tenant equivalent."""
    token = set_current_tenant(TenantContext(tenant_id=tenant_id, slug=slug, isolation=isolation))
    try:
        yield
    finally:
        reset_current_tenant(token)


class RequireCurrentTenantError(Exception):
    pass


def require_current_tenant() -> TenantContext:
    ctx = get_current_tenant()
    if ctx is None:
        raise RequireCurrentTenantError("No tenant context is set for this request/task")
    return ctx
