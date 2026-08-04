import uuid

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

engine = create_engine(settings.DATABASE_URL)
TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr("app.candidates.storage.UPLOAD_DIR", tmp_path / "resumes")


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
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
