"""TenantTask (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2): the base class every Celery
task that touches tenant data extends instead of celery.Task -- requires a `tenant_id`
task header, sets TenantContext before the task body runs, and resets it after. Mirrors
what TenantResolverMiddleware does for an HTTP request, for a background task instead.
"""

import os
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
        slot = _acquire_tenant_slot(tenant_id)
        if slot is False:
            # Noisy-tenant protection (Part 13 section C): this tenant already has its
            # maximum number of jobs running -- requeue with a short delay instead of taking
            # a worker slot another tenant could use.
            raise self.retry(countdown=15, max_retries=None)
        token = set_current_tenant(ctx)
        try:
            return super().__call__(*args, **kwargs)
        finally:
            reset_current_tenant(token)
            _release_tenant_slot(tenant_id, slot)


TENANT_MAX_CONCURRENT_JOBS = int(os.getenv("TENANT_MAX_CONCURRENT_JOBS", "4"))


def _acquire_tenant_slot(tenant_id: str):
    """None = no limiter (no Redis / eager mode); True = slot taken; False = at the cap."""
    from app.core.config import settings

    if not settings.REDIS_URL or settings.CELERY_ALWAYS_EAGER:
        return None
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.5)
        key = f"t:{tenant_id}:jobs:running"
        running = client.incr(key)
        client.expire(key, 3600)  # a crashed worker can't hold a slot forever
        if running > TENANT_MAX_CONCURRENT_JOBS:
            client.decr(key)
            return False
        return True
    except Exception:
        return None  # limiter unavailable -> run rather than stall every tenant's jobs


def _release_tenant_slot(tenant_id: str, slot) -> None:
    if slot is not True:
        return
    try:
        import redis

        from app.core.config import settings

        redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.5).decr(f"t:{tenant_id}:jobs:running")
    except Exception:
        pass


def apply_for_tenant(task, tenant_id: UUID, *args, **kwargs):
    """The one supported way to dispatch a TenantTask -- sets the tenant_id header
    __call__ above requires, so a caller can never forget it and get a confusing failure
    deep inside the task body instead."""
    return task.apply_async(args=args, kwargs=kwargs, headers={"tenant_id": str(tenant_id)})
