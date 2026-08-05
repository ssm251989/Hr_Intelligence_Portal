from app.core.crypto import decrypt, encrypt
from app.core.security import create_access_token
from app.integrations.google_calendar import GoogleCalendarError
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.user_integration import UserIntegration


def _make_user(db_session, email="oauth-user@example.com", role="interviewer") -> User:
    user = User(email=email, hashed_password="x", role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_connect_returns_google_auth_url_as_json(client, monkeypatch):
    captured = {}

    def fake_build_authorization_url(state):
        captured["state"] = state
        return "https://accounts.google.com/o/oauth2/auth?fake=1"

    monkeypatch.setattr("app.integrations.router.build_authorization_url", fake_build_authorization_url)

    response = client.get("/integrations/google/connect")

    assert response.status_code == 200
    assert response.json() == {"auth_url": "https://accounts.google.com/o/oauth2/auth?fake=1"}
    assert captured["state"]  # a state token was generated and passed through


def test_connect_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/google/connect")
    assert response.status_code == 401


def test_google_callback_stores_encrypted_refresh_token(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session)
    state = create_access_token(subject=str(user.id))
    monkeypatch.setattr(
        "app.integrations.router.exchange_code_for_refresh_token", lambda code: "fake-refresh-token"
    )

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200

    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "google")
        .one()
    )
    assert integration.refresh_token != "fake-refresh-token"
    assert decrypt(integration.refresh_token) == "fake-refresh-token"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == user.id, AuditLog.action == "google_calendar_connected")
        .one_or_none()
    )
    assert audit_entry is not None


def test_google_callback_reconnect_overwrites_existing_token(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="reconnect@example.com")
    db_session.add(UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt("old-token")))
    db_session.commit()

    state = create_access_token(subject=str(user.id))
    monkeypatch.setattr(
        "app.integrations.router.exchange_code_for_refresh_token", lambda code: "new-refresh-token"
    )

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200
    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "google")
        .one()
    )
    assert decrypt(integration.refresh_token) == "new-refresh-token"


def test_google_callback_rejects_invalid_state(anonymous_client):
    response = anonymous_client.get(
        "/auth/google/callback", params={"code": "fake-code", "state": "not-a-real-jwt"}
    )
    assert response.status_code == 400


def test_google_callback_surfaces_token_exchange_failure(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="exchange-fail@example.com")
    state = create_access_token(subject=str(user.id))

    def fake_exchange(code):
        raise GoogleCalendarError("boom")

    monkeypatch.setattr("app.integrations.router.exchange_code_for_refresh_token", fake_exchange)

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 400


def test_google_callback_unknown_user_returns_404(anonymous_client):
    import uuid

    state = create_access_token(subject=str(uuid.uuid4()))
    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})
    assert response.status_code == 404


def test_status_not_connected(client):
    response = client.get("/integrations/google/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["connected_at"] is None


def test_status_connected(client, db_session):
    admin = db_session.query(User).filter(User.email == "test-admin@example.com").one()
    db_session.add(UserIntegration(user_id=admin.id, provider="google", refresh_token=encrypt("tok")))
    db_session.commit()

    response = client.get("/integrations/google/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["connected_at"] is not None


def test_status_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/google/status")
    assert response.status_code == 401
