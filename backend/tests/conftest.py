import os
import uuid

# Part 13: the whole suite shares one process-local rate-limit counter; tests that exercise
# the limiter itself enable it explicitly via monkeypatch.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  -- registers all models on Base.metadata
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User
from app.platform.tenancy.context import TenantContext, TENANT_1_ID, reset_current_tenant, set_current_tenant

# The app's own runtime DSN (a non-superuser role -- RLS actually applies to it, unlike
# settings.DATABASE_URL's Postgres superuser, which Postgres always exempts from row
# security regardless of FORCE). Tests run against the real RLS policies, not a
# superuser connection that would silently make them a no-op.
engine = create_engine(settings.APP_DATABASE_URL)
TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr("app.candidates.storage.UPLOAD_DIR", tmp_path / "resumes")
    monkeypatch.setattr("app.candidates.storage.PHOTO_UPLOAD_DIR", tmp_path / "candidate-photos")
    monkeypatch.setattr("app.onboarding.portal.UPLOAD_DIR", tmp_path / "onboarding")
    # Part G's ready-to-upload/already-uploaded roots are DB-configured (local_import_
    # settings), not fixed module paths -- nothing to isolate here globally. Tests that
    # exercise the scan configure their own tmp_path roots via that settings row (see
    # test_local_import.py's configured_roots fixture), isolated the same way every other
    # DB row is: db_session's own rolled-back transaction.


@pytest.fixture(autouse=True)
def _default_tenant_context():
    """Part 2: every existing test implicitly assumes "the" tenant (#1) -- this mirrors
    what TenantResolverMiddleware sets for every real request under TENANCY_MODE=single,
    so TenantOwned's before_insert auto-populate hook (and anything else that reads
    get_current_tenant()) behaves the same in a test that builds rows directly via
    db_session as it does for a real request. A test that goes through `client`
    (TestClient -> the real middleware stack) gets this OVERWRITTEN by the middleware's own
    control-plane lookup for the duration of that request, which resolves to the same
    tenant #1 anyway (see hrctl.tenant's bootstrap-existing, already run once for this
    repo's own dev control-plane database)."""
    token = set_current_tenant(TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db"))
    yield
    reset_current_tenant(token)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """platform/settings/resolver.py's in-process cache (see its own module docstring --
    no Redis instance provisioned) is a process-level global, so a value written by one
    test's db_session (rolled back at that test's own teardown, never really persisted)
    would otherwise leak into every later test that reads the same key. Global/autouse
    rather than something only test_settings_resolver.py itself worries about -- ANY test
    that happens to call SettingsService.set() (directly, or indirectly through
    application code) can pollute it for every other test file too."""
    from app.platform.settings.resolver import clear_all_cache

    clear_all_cache()
    yield
    clear_all_cache()


@pytest.fixture()
def db_session(_default_tenant_context):
    # app.core.database's own SessionLocal "after_begin" event (see its comment) applies
    # `SET LOCAL app.tenant_id` from _default_tenant_context automatically the moment this
    # session's first statement opens its transaction -- nothing extra needed here.
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


control_plane_engine = create_engine(settings.APP_CONTROL_PLANE_DATABASE_URL)
ControlPlaneTestingSessionLocal = sessionmaker(bind=control_plane_engine)


@pytest.fixture()
def control_plane_db_session():
    """Same rolled-back-transaction isolation as db_session, but against the control-plane
    database -- for tests that create/mutate Tenant/TenantDomain rows without permanently
    touching this repo's own dev control plane (which already has a real, permanent tenant
    #1 row from hrctl.tenant bootstrap-existing -- see _default_tenant_context)."""
    connection = control_plane_engine.connect()
    transaction = connection.begin()
    session = ControlPlaneTestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def _create_user(db_session, role="admin", email=None) -> User:
    user = User(
        email=email or f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("testpassword123"),
        full_name="Test User",
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Part 5A: bridge_single_user is normally called from the two real user-creation
    # endpoints (auth/router.py's register(), users/router.py's create_user()) -- this
    # helper builds users directly via the ORM instead, so it needs the same call, or
    # every test using `client`/`make_auth_headers` would get a flat `role` the OLD
    # require_roles() honors but the NEW authz.require() resolves to zero permissions for.
    from app.platform.iam.roles import bridge_single_user

    bridge_single_user(db_session, TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db"), user)
    return user


@pytest.fixture()
def make_auth_headers(db_session):
    """Create a user with the given role and return an Authorization header for them."""

    def _make(role="admin", email=None):
        user = _create_user(db_session, role=role, email=email)
        token = create_access_token(subject=str(user.id))
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture()
def anonymous_client(db_session):
    """A TestClient with no Authorization header, for auth/rejection tests."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client(db_session):
    # Defaults to an authenticated admin session so existing business-logic
    # tests (written before auth existed) don't need to manage tokens
    # themselves -- admin passes every role check. Auth-specific rejection
    # tests use `anonymous_client` / `make_auth_headers` instead.
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        admin = _create_user(db_session, role="admin", email="test-admin@example.com")
        token = create_access_token(subject=str(admin.id))
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    app.dependency_overrides.clear()
