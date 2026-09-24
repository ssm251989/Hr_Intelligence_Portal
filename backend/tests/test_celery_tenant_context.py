"""platform/jobs/tenant_task.py -- TenantTask sets/resets TenantContext around a task body
(Part 2 CHECKS). task_always_eager=True (celery_app.py) means .delay()/apply_for_tenant()
run the task body synchronously in-process here, with no live worker needed."""

import uuid

import pytest

from app.platform.jobs.celery_app import celery_app
from app.platform.jobs.tenant_task import MissingTenantHeaderError, UnknownTenantError, TenantTask, apply_for_tenant
from app.platform.tenancy.context import TENANT_1_ID, get_current_tenant


@celery_app.task(base=TenantTask, bind=True)
def _whoami_task(self):
    ctx = get_current_tenant()
    return {"tenant_id": str(ctx.tenant_id), "slug": ctx.slug} if ctx else None


def test_apply_for_tenant_sets_tenant_context_for_the_task_body():
    result = apply_for_tenant(_whoami_task, TENANT_1_ID)
    assert result.get()["tenant_id"] == str(TENANT_1_ID)
    assert result.get()["slug"] == "ctd-techs"


def test_context_is_reset_after_the_task_completes():
    """Every test already runs inside conftest.py's own default TenantContext (slug
    "tenant1-test") -- the task body sees a DIFFERENT context (slug "ctd-techs", the real
    control-plane row apply_for_tenant loads), proving reset restores whatever was active
    before the task ran, not just unconditionally clears to None."""
    before = get_current_tenant()
    assert before is not None and before.slug == "tenant1-test"

    result = apply_for_tenant(_whoami_task, TENANT_1_ID).get()
    assert result["slug"] == "ctd-techs"

    after = get_current_tenant()
    assert after is before


def test_calling_delay_directly_without_a_tenant_header_raises():
    """The whole point of apply_for_tenant() existing -- calling .delay() directly (the
    ordinary Celery way) skips the header it requires, and must fail loudly rather than
    silently run with no tenant context at all."""
    with pytest.raises(MissingTenantHeaderError):
        _whoami_task.delay()


def test_apply_for_tenant_with_an_unknown_tenant_id_raises():
    with pytest.raises(UnknownTenantError):
        apply_for_tenant(_whoami_task, uuid.uuid4())
