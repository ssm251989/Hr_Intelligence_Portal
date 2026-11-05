"""platform/tenancy/middleware.py -- host, header, suspended, jwt-tid-mismatch 403 (Part 2
CHECKS: host, header, jwt mismatch 403, suspended 423)."""

import uuid

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.security import create_access_token
from app.platform.tenancy.context import get_current_tenant
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.middleware import TenantResolverMiddleware, clear_single_tenant_cache
from app.platform.tenancy.models_cp import Tenant, TenantDomain


def _make_tenant(control_plane_db_session, *, slug, status="active", suspended_reason=None) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), slug=slug, display_name=slug, status=status, isolation="dedicated_db", suspended_reason=suspended_reason)
    control_plane_db_session.add(tenant)
    control_plane_db_session.commit()
    control_plane_db_session.refresh(tenant)
    return tenant


class _FakeRequest:
    def __init__(self, headers: dict):
        self.headers = headers


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_single_tenant_cache()
    yield
    clear_single_tenant_cache()


def test_resolve_by_host_header_in_multi_mode(control_plane_db_session, monkeypatch):
    monkeypatch.setattr("app.platform.tenancy.middleware.settings.TENANCY_MODE", "multi")
    tenant = _make_tenant(control_plane_db_session, slug="acme")
    domain = TenantDomain(tenant_id=tenant.id, host="acme.example.com", is_primary=True)
    control_plane_db_session.add(domain)
    control_plane_db_session.commit()

    resolved = TenantResolverMiddleware(app=None)._resolve(
        _FakeRequest({"host": "acme.example.com:8000"}), control_plane_db_session
    )
    assert resolved is not None
    assert resolved.id == tenant.id


def test_resolve_by_x_tenant_slug_header_in_multi_mode(control_plane_db_session, monkeypatch):
    monkeypatch.setattr("app.platform.tenancy.middleware.settings.TENANCY_MODE", "multi")
    tenant = _make_tenant(control_plane_db_session, slug="beta-co")

    resolved = TenantResolverMiddleware(app=None)._resolve(
        _FakeRequest({"x-tenant-slug": "beta-co"}), control_plane_db_session
    )
    assert resolved is not None
    assert resolved.id == tenant.id


def test_resolve_returns_none_for_unknown_host_and_no_header_in_multi_mode(control_plane_db_session, monkeypatch):
    monkeypatch.setattr("app.platform.tenancy.middleware.settings.TENANCY_MODE", "multi")
    resolved = TenantResolverMiddleware(app=None)._resolve(_FakeRequest({"host": "nobody.example.com"}), control_plane_db_session)
    assert resolved is None


def test_single_mode_resolves_the_one_tenant_regardless_of_headers(control_plane_db_session):
    # TENANCY_MODE stays "single" (this repo's own real deployment shape, and this test's
    # default) -- the real, permanent tenant #1 row (hrctl.tenant bootstrap-existing) is
    # what this must resolve to, not anything in control_plane_db_session's own rolled-back
    # transaction, since single mode ignores host/header entirely.
    resolved = TenantResolverMiddleware(app=None)._resolve(_FakeRequest({}), control_plane_db_session)
    assert resolved is not None
    assert resolved.slug == "ctd-techs"


def _build_test_app():
    async def whoami(request):
        ctx = get_current_tenant()
        return JSONResponse({"tenant_id": str(ctx.tenant_id) if ctx else None, "slug": ctx.slug if ctx else None})

    app = Starlette(routes=[Route("/whoami", whoami)])
    app.add_middleware(TenantResolverMiddleware)
    return app


def test_dispatch_returns_423_for_a_suspended_tenant(monkeypatch):
    # dispatch() below opens its OWN fresh ControlPlaneSessionLocal() connection (see
    # middleware.py) -- a row only visible to it once genuinely committed, unlike
    # control_plane_db_session's rolled-back-transaction isolation (which a separate
    # connection never sees at all). Uses the real sessionmaker directly with explicit
    # cleanup instead, for this one test that specifically needs cross-connection
    # visibility to exercise the real dispatch() path end to end.
    monkeypatch.setattr("app.platform.tenancy.middleware.settings.TENANCY_MODE", "multi")
    db = ControlPlaneSessionLocal()
    tenant = _make_tenant(db, slug="suspended-co", status="suspended", suspended_reason="Payment overdue")
    db.close()
    try:
        test_app = _build_test_app()
        with TestClient(test_app, base_url="http://testserver") as client:
            response = client.get("/whoami", headers={"x-tenant-slug": "suspended-co"})
        assert response.status_code == 423
        assert response.json()["detail"] == "Payment overdue"
    finally:
        cleanup_db = ControlPlaneSessionLocal()
        cleanup_db.query(Tenant).filter(Tenant.id == tenant.id).delete()
        cleanup_db.commit()
        cleanup_db.close()


def test_dispatch_returns_404_for_an_unresolvable_tenant(monkeypatch):
    monkeypatch.setattr("app.platform.tenancy.middleware.settings.TENANCY_MODE", "multi")
    test_app = _build_test_app()
    with TestClient(test_app, base_url="http://testserver") as client:
        response = client.get("/whoami")
    assert response.status_code == 404


def test_a_token_issued_for_a_different_tenant_is_rejected(client, make_auth_headers):
    """The real /auth/login path embeds tid (see auth/router.py) -- get_current_user must
    reject a token whose tid disagrees with the tenant THIS request resolved to. Simulated
    directly (rather than standing up a second real tenant + login) by hand-crafting a
    token with a tid that can never match tenant #1."""
    mismatched_token = create_access_token(subject=str(uuid.uuid4()), extra_claims={"tid": str(uuid.uuid4())})
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {mismatched_token}"})
    assert response.status_code == 403


def test_a_token_with_no_tid_claim_is_not_treated_as_a_mismatch(make_auth_headers, client):
    """Every existing test helper (create_access_token without extra_claims) must keep
    working -- see auth/dependencies.py's own comment on why this is deliberately
    permissive for a token that simply never carries a tid at all."""
    headers = make_auth_headers(role="admin")
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
