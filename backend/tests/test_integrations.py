import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from app.core.crypto import decrypt, encrypt
from app.core.security import create_access_token, decode_access_token
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

    def fake_build_authorization_url(state, code_verifier):
        captured["state"] = state
        captured["code_verifier"] = code_verifier
        return "https://accounts.google.com/o/oauth2/auth?fake=1"

    monkeypatch.setattr("app.integrations.router.build_authorization_url", fake_build_authorization_url)

    response = client.get("/integrations/google/connect")

    assert response.status_code == 200
    assert response.json() == {"auth_url": "https://accounts.google.com/o/oauth2/auth?fake=1"}
    assert captured["state"]  # a state token was generated and passed through
    assert captured["code_verifier"]


def test_connect_state_round_trips_code_verifier(client):
    # Uses the real build_authorization_url (no network call -- it's a local URL
    # construction) to prove the code_verifier embedded in `state` is the same one whose
    # S256 hash was sent to Google as code_challenge. If these ever diverge, /callback's
    # token exchange fails with "(invalid_grant) Missing code verifier."
    response = client.get("/integrations/google/connect")

    assert response.status_code == 200
    auth_url = response.json()["auth_url"]
    query = parse_qs(urlparse(auth_url).query)
    state = query["state"][0]
    code_challenge = query["code_challenge"][0]

    payload = decode_access_token(state)
    code_verifier = payload["code_verifier"]

    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    assert code_challenge == expected_challenge


def test_connect_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/google/connect")
    assert response.status_code == 401


def test_google_callback_stores_encrypted_refresh_token(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session)
    state = create_access_token(subject=str(user.id), extra_claims={"code_verifier": "test-verifier"})
    captured = {}

    def fake_exchange(code, code_verifier):
        captured["code"] = code
        captured["code_verifier"] = code_verifier
        return "fake-refresh-token"

    monkeypatch.setattr("app.integrations.router.exchange_code_for_refresh_token", fake_exchange)

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200
    # The code_verifier that made the round trip through `state` reaches the token exchange.
    assert captured == {"code": "fake-code", "code_verifier": "test-verifier"}

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

    state = create_access_token(subject=str(user.id), extra_claims={"code_verifier": "test-verifier"})
    monkeypatch.setattr(
        "app.integrations.router.exchange_code_for_refresh_token",
        lambda code, code_verifier: "new-refresh-token",
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
    state = create_access_token(subject=str(user.id), extra_claims={"code_verifier": "test-verifier"})

    def fake_exchange(code, code_verifier):
        raise GoogleCalendarError("boom")

    monkeypatch.setattr("app.integrations.router.exchange_code_for_refresh_token", fake_exchange)

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 400


def test_google_callback_unknown_user_returns_404(anonymous_client):
    import uuid

    state = create_access_token(subject=str(uuid.uuid4()), extra_claims={"code_verifier": "test-verifier"})
    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})
    assert response.status_code == 404


def test_google_callback_state_missing_code_verifier_returns_400(anonymous_client, db_session):
    # A state token from before this fix (or otherwise malformed) has no code_verifier claim.
    user = _make_user(db_session, email="missing-verifier@example.com")
    state = create_access_token(subject=str(user.id))

    response = anonymous_client.get("/auth/google/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 400


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


def test_status_for_another_user_via_user_id(client, db_session):
    # A recruiter checking whether the interviewer they're about to assign is connected.
    other = _make_user(db_session, email="other-connected@example.com")
    db_session.add(UserIntegration(user_id=other.id, provider="google", refresh_token=encrypt("tok")))
    db_session.commit()

    response = client.get(f"/integrations/google/status?user_id={other.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True

    # The caller's own status is untouched -- caller (admin) has no integration.
    own_status = client.get("/integrations/google/status")
    assert own_status.json()["connected"] is False


def test_status_for_another_user_not_connected(client, db_session):
    other = _make_user(db_session, email="other-not-connected@example.com")

    response = client.get(f"/integrations/google/status?user_id={other.id}")

    assert response.status_code == 200
    assert response.json()["connected"] is False
