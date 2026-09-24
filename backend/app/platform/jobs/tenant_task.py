"""TenantTask (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2): the base class every Celery
task that touches tenant data extends instead of celery.Task -- requires a `tenant_id`
task header, sets TenantContext before the task body runs, and resets it after. Mirrors
what TenantResolverMiddleware does for an HTTP request, for a background task instead.
"""

from uuid import UUID

from celery import Task

from app.platform.tenancy.context import TenantContext, reset_current_tenant, set_current_tenant
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import Tenant


class MissingTenantHeaderError(Exception):
    pass


class UnknownTenantError(Exception):
    pass


def _load_tenant_context(tenant_id: str) -> TenantContext:
    db = ControlPlaneSessionLocal()
    try:
        tenant = db.get(Tenant, UUID(tenant_id))
        if tenant is None:
            raise UnknownTenantError(tenant_id)
        return TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)
    finally:
        db.close()


class TenantTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        headers = self.request.headers or {}
        tenant_id = headers.get("tenant_id")
        if tenant_id is None:
            raise MissingTenantHeaderError(
                f"{self.name} requires a tenant_id header -- use apply_for_tenant() to dispatch it"
            )
        ctx = _load_tenant_context(tenant_id)
        token = set_current_tenant(ctx)
        try:
            return super().__call__(*args, **kwargs)
        finally:
            reset_current_tenant(token)


def apply_for_tenant(task, tenant_id: UUID, *args, **kwargs):
    """The one supported way to dispatch a TenantTask -- sets the tenant_id header
    __call__ above requires, so a caller can never forget it and get a confusing failure
    deep inside the task body instead."""
    return task.apply_async(args=args, kwargs=kwargs, headers={"tenant_id": str(tenant_id)})
