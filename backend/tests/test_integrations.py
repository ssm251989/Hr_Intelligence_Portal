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


# --- DocuSign -----------------------------------------------------------------
# Mirrors the Google Calendar OAuth flow tests above, minus PKCE (DocuSign uses a
# standard Authorization Code Grant here).


def test_docusign_connect_returns_auth_url_as_json(client, monkeypatch):
    captured = {}

    def fake_build_authorization_url(state):
        captured["state"] = state
        return "https://account-d.docusign.com/oauth/auth?fake=1"

    monkeypatch.setattr("app.integrations.router.build_docusign_authorization_url", fake_build_authorization_url)

    response = client.get("/integrations/docusign/connect")

    assert response.status_code == 200
    assert response.json() == {"auth_url": "https://account-d.docusign.com/oauth/auth?fake=1"}
    assert captured["state"]


def test_docusign_connect_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/docusign/connect")
    assert response.status_code == 401


def test_docusign_callback_stores_encrypted_refresh_token(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="docusign-oauth-user@example.com")
    state = create_access_token(subject=str(user.id))
    captured = {}

    def fake_exchange(code):
        captured["code"] = code
        return "fake-docusign-refresh-token"

    monkeypatch.setattr("app.integrations.router.exchange_docusign_code_for_refresh_token", fake_exchange)

    response = anonymous_client.get("/auth/docusign/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200
    assert captured == {"code": "fake-code"}

    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "docusign")
        .one()
    )
    assert integration.refresh_token != "fake-docusign-refresh-token"
    assert decrypt(integration.refresh_token) == "fake-docusign-refresh-token"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == user.id, AuditLog.action == "docusign_connected")
        .one_or_none()
    )
    assert audit_entry is not None


def test_docusign_callback_reconnect_overwrites_existing_token(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="docusign-reconnect@example.com")
    db_session.add(UserIntegration(user_id=user.id, provider="docusign", refresh_token=encrypt("old-token")))
    db_session.commit()

    state = create_access_token(subject=str(user.id))
    monkeypatch.setattr(
        "app.integrations.router.exchange_docusign_code_for_refresh_token",
        lambda code: "new-refresh-token",
    )

    response = anonymous_client.get("/auth/docusign/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200
    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "docusign")
        .one()
    )
    assert decrypt(integration.refresh_token) == "new-refresh-token"

    # The existing Google integration path is untouched by this provider-parameterized helper.
    google_integrations = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "google")
        .all()
    )
    assert google_integrations == []


def test_docusign_callback_rejects_invalid_state(anonymous_client):
    response = anonymous_client.get(
        "/auth/docusign/callback", params={"code": "fake-code", "state": "not-a-real-jwt"}
    )
    assert response.status_code == 400


def test_docusign_callback_surfaces_token_exchange_failure(anonymous_client, db_session, monkeypatch):
    from app.integrations.docusign import DocuSignError

    user = _make_user(db_session, email="docusign-exchange-fail@example.com")
    state = create_access_token(subject=str(user.id))

    def fake_exchange(code):
        raise DocuSignError("boom")

    monkeypatch.setattr("app.integrations.router.exchange_docusign_code_for_refresh_token", fake_exchange)

    response = anonymous_client.get("/auth/docusign/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 400


def test_docusign_callback_unknown_user_returns_404(anonymous_client):
    import uuid

    state = create_access_token(subject=str(uuid.uuid4()))
    response = anonymous_client.get("/auth/docusign/callback", params={"code": "fake-code", "state": state})
    assert response.status_code == 404


def test_docusign_status_not_connected(client):
    response = client.get("/integrations/docusign/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["connected_at"] is None


def test_docusign_status_connected(client, db_session):
    admin = db_session.query(User).filter(User.email == "test-admin@example.com").one()
    db_session.add(UserIntegration(user_id=admin.id, provider="docusign", refresh_token=encrypt("tok")))
    db_session.commit()

    response = client.get("/integrations/docusign/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["connected_at"] is not None


def test_docusign_status_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/docusign/status")
    assert response.status_code == 401


def test_docusign_and_google_status_are_independent(client, db_session):
    # Connecting DocuSign must not report as Google being connected, and vice versa --
    # this exercises the provider-parameterized _get_integration helper shared by both.
    admin = db_session.query(User).filter(User.email == "test-admin@example.com").one()
    db_session.add(UserIntegration(user_id=admin.id, provider="docusign", refresh_token=encrypt("tok")))
    db_session.commit()

    docusign_status = client.get("/integrations/docusign/status")
    google_status = client.get("/integrations/google/status")

    assert docusign_status.json()["connected"] is True
    assert google_status.json()["connected"] is False


# --- LinkedIn -------------------------------------------------------------------
# Mirrors the DocuSign OAuth flow tests above (standard Authorization Code Grant, no
# PKCE), plus LinkedIn-specific bits: storing the member URN and access-token expiry.


def test_linkedin_connect_returns_auth_url_as_json(client, monkeypatch):
    captured = {}

    def fake_build_authorization_url(state):
        captured["state"] = state
        return "https://www.linkedin.com/oauth/v2/authorization?fake=1"

    monkeypatch.setattr("app.integrations.router.build_linkedin_authorization_url", fake_build_authorization_url)

    response = client.get("/integrations/linkedin/connect")

    assert response.status_code == 200
    assert response.json() == {"auth_url": "https://www.linkedin.com/oauth/v2/authorization?fake=1"}
    assert captured["state"]


def test_linkedin_connect_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/linkedin/connect")
    assert response.status_code == 401


def test_linkedin_callback_stores_encrypted_token_and_member_urn(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="linkedin-oauth-user@example.com")
    state = create_access_token(subject=str(user.id))

    monkeypatch.setattr(
        "app.integrations.router.exchange_linkedin_code_for_access_token",
        lambda code: {"access_token": "fake-linkedin-token", "expires_in": 5184000},
    )
    monkeypatch.setattr("app.integrations.router.get_member_urn", lambda access_token: "urn:li:person:abc123")

    response = anonymous_client.get("/auth/linkedin/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200

    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "linkedin")
        .one()
    )
    assert integration.refresh_token != "fake-linkedin-token"
    assert decrypt(integration.refresh_token) == "fake-linkedin-token"
    assert integration.provider_metadata == {"member_urn": "urn:li:person:abc123"}
    assert integration.expires_at is not None

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == user.id, AuditLog.action == "linkedin_connected")
        .one_or_none()
    )
    assert audit_entry is not None


def test_linkedin_callback_reconnect_overwrites_existing_token_and_urn(anonymous_client, db_session, monkeypatch):
    user = _make_user(db_session, email="linkedin-reconnect@example.com")
    db_session.add(
        UserIntegration(
            user_id=user.id, provider="linkedin", refresh_token=encrypt("old-token"),
            provider_metadata={"member_urn": "urn:li:person:old"},
        )
    )
    db_session.commit()

    state = create_access_token(subject=str(user.id))
    monkeypatch.setattr(
        "app.integrations.router.exchange_linkedin_code_for_access_token",
        lambda code: {"access_token": "new-token", "expires_in": 5184000},
    )
    monkeypatch.setattr("app.integrations.router.get_member_urn", lambda access_token: "urn:li:person:new")

    response = anonymous_client.get("/auth/linkedin/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 200
    integration = (
        db_session.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "linkedin")
        .one()
    )
    assert decrypt(integration.refresh_token) == "new-token"
    assert integration.provider_metadata == {"member_urn": "urn:li:person:new"}


def test_linkedin_callback_rejects_invalid_state(anonymous_client):
    response = anonymous_client.get(
        "/auth/linkedin/callback", params={"code": "fake-code", "state": "not-a-real-jwt"}
    )
    assert response.status_code == 400


def test_linkedin_callback_surfaces_token_exchange_failure(anonymous_client, db_session, monkeypatch):
    from app.integrations.linkedin import LinkedInError

    user = _make_user(db_session, email="linkedin-exchange-fail@example.com")
    state = create_access_token(subject=str(user.id))

    def fake_exchange(code):
        raise LinkedInError("boom")

    monkeypatch.setattr("app.integrations.router.exchange_linkedin_code_for_access_token", fake_exchange)

    response = anonymous_client.get("/auth/linkedin/callback", params={"code": "fake-code", "state": state})

    assert response.status_code == 400


def test_linkedin_callback_unknown_user_returns_404(anonymous_client):
    import uuid

    state = create_access_token(subject=str(uuid.uuid4()))
    response = anonymous_client.get("/auth/linkedin/callback", params={"code": "fake-code", "state": state})
    assert response.status_code == 404


def test_linkedin_status_not_connected(client):
    response = client.get("/integrations/linkedin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["connected_at"] is None
    assert body["expired"] is None


def test_linkedin_status_connected_not_expired(client, db_session):
    admin = db_session.query(User).filter(User.email == "test-admin@example.com").one()
    from datetime import datetime, timedelta, timezone

    db_session.add(
        UserIntegration(
            user_id=admin.id, provider="linkedin", refresh_token=encrypt("tok"),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            provider_metadata={"member_urn": "urn:li:person:admin"},
        )
    )
    db_session.commit()

    response = client.get("/integrations/linkedin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["expired"] is False


def test_linkedin_status_connected_but_expired(client, db_session):
    admin = db_session.query(User).filter(User.email == "test-admin@example.com").one()
    from datetime import datetime, timedelta, timezone

    db_session.add(
        UserIntegration(
            user_id=admin.id, provider="linkedin", refresh_token=encrypt("tok"),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            provider_metadata={"member_urn": "urn:li:person:admin"},
        )
    )
    db_session.commit()

    response = client.get("/integrations/linkedin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["expired"] is True


def test_linkedin_status_requires_authentication(anonymous_client):
    response = anonymous_client.get("/integrations/linkedin/status")
    assert response.status_code == 401


# --- HR mailbox: the single shared, org-level mailbox (app/integrations/hr_email.py,
# app/hr_inbox/router.py) -- plain SMTP/IMAP credentials rather than a Google OAuth
# connection. Configuring it is admin-only; the settings land on the hr_integrations
# singleton row (id=1) rather than any admin's own UserIntegration.


def _reset_hr_integration(db_session):
    from app.models.hr_integration import HrIntegration

    row = db_session.get(HrIntegration, 1)
    if row is not None:
        row.smtp_host = None
        row.smtp_port = None
        row.use_tls = None
        row.smtp_username = None
        row.smtp_password = None
        row.from_address = None
        row.hr_module_email = None
        row.imap_host = None
        row.imap_port = None
        row.use_ssl = None
        row.imap_last_uid = None
        db_session.commit()


def test_hr_inbox_settings_get_requires_admin_role(client, make_auth_headers):
    headers = make_auth_headers(role="recruiter", email="non-admin-settings@example.com")
    response = client.get("/hr-inbox/settings", headers=headers)
    assert response.status_code == 403


def test_hr_inbox_settings_get_requires_authentication(anonymous_client):
    response = anonymous_client.get("/hr-inbox/settings")
    assert response.status_code == 401


def test_hr_inbox_settings_get_reports_unconfigured_by_default(client, db_session):
    # `client` defaults to an admin session (see conftest.py) -- admin passes the
    # admin-only check on this endpoint.
    _reset_hr_integration(db_session)

    response = client.get("/hr-inbox/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["smtp_configured"] is False
    assert body["imap_configured"] is False


def test_hr_inbox_settings_update_requires_admin_role(client, make_auth_headers):
    headers = make_auth_headers(role="recruiter", email="non-admin-update@example.com")
    response = client.put("/hr-inbox/settings", json={"smtp_host": "smtp.example.com"}, headers=headers)
    assert response.status_code == 403


def test_hr_inbox_settings_update_stores_and_encrypts_password_never_returning_it(client, db_session):
    _reset_hr_integration(db_session)

    response = client.put(
        "/hr-inbox/settings",
        json={
            "smtp_host": "smtp.example.com", "smtp_port": 587, "use_tls": True,
            "smtp_username": "hr@example.com", "smtp_password": "super-secret-password",
            "from_address": "hr@example.com", "hr_module_email": "hr-module@example.com",
            "imap_host": "imap.example.com", "imap_port": 993, "use_ssl": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["smtp_configured"] is True
    assert body["imap_configured"] is True
    assert "smtp_password" not in body
    assert body["smtp_host"] == "smtp.example.com"
    assert body["hr_module_email"] == "hr-module@example.com"

    from app.models.hr_integration import HrIntegration

    row = db_session.get(HrIntegration, 1)
    assert row.smtp_password != "super-secret-password"
    assert decrypt(row.smtp_password) == "super-secret-password"


def test_hr_inbox_settings_update_omitted_password_leaves_existing_one_unchanged(client, db_session):
    _reset_hr_integration(db_session)
    client.put(
        "/hr-inbox/settings",
        json={"smtp_host": "smtp.example.com", "smtp_username": "hr@example.com", "smtp_password": "first-password"},
    )

    response = client.put("/hr-inbox/settings", json={"from_address": "hr2@example.com"})

    assert response.status_code == 200
    assert response.json()["from_address"] == "hr2@example.com"

    from app.models.hr_integration import HrIntegration

    row = db_session.get(HrIntegration, 1)
    assert decrypt(row.smtp_password) == "first-password"


def test_hr_inbox_send_test_email_requires_smtp_configured(client, db_session):
    _reset_hr_integration(db_session)

    response = client.post("/hr-inbox/settings/send-test-email", json={"to": "someone@example.com"})

    assert response.status_code == 400


def test_hr_inbox_send_test_email_success(client, db_session, monkeypatch):
    _reset_hr_integration(db_session)
    client.put(
        "/hr-inbox/settings",
        json={"smtp_host": "smtp.example.com", "smtp_username": "hr@example.com", "smtp_password": "pw"},
    )
    captured = {}
    monkeypatch.setattr(
        "app.hr_inbox.router.send_hr_email",
        lambda hr_integration, **kwargs: captured.update(kwargs),
    )

    response = client.post("/hr-inbox/settings/send-test-email", json={"to": "someone@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is True
    assert captured["to"] == "someone@example.com"


def test_hr_inbox_send_test_email_smtp_failure_reported_inline_not_502(client, db_session, monkeypatch):
    from app.integrations.hr_email import SmtpError

    _reset_hr_integration(db_session)
    client.put(
        "/hr-inbox/settings",
        json={"smtp_host": "smtp.example.com", "smtp_username": "hr@example.com", "smtp_password": "pw"},
    )
    monkeypatch.setattr(
        "app.hr_inbox.router.send_hr_email",
        lambda *a, **k: (_ for _ in ()).throw(SmtpError("Connection refused")),
    )

    response = client.post("/hr-inbox/settings/send-test-email", json={"to": "someone@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is False
    assert "Connection refused" in body["detail"]


def test_hr_inbox_send_test_email_requires_admin_role(client, make_auth_headers):
    headers = make_auth_headers(role="recruiter", email="non-admin-test-email@example.com")
    response = client.post("/hr-inbox/settings/send-test-email", json={"to": "someone@example.com"}, headers=headers)
    assert response.status_code == 403


def test_hr_inbox_test_imap_connection_requires_imap_configured(client, db_session):
    _reset_hr_integration(db_session)

    response = client.post("/hr-inbox/settings/test-imap-connection")

    assert response.status_code == 400


def test_hr_inbox_test_imap_connection_success(client, db_session, monkeypatch):
    _reset_hr_integration(db_session)
    client.put(
        "/hr-inbox/settings",
        json={
            "smtp_username": "hr@example.com", "smtp_password": "pw",
            "imap_host": "imap.example.com", "imap_port": 993, "use_ssl": True,
        },
    )
    monkeypatch.setattr("app.hr_inbox.router.test_imap_connection", lambda hr_integration: None)

    response = client.post("/hr-inbox/settings/test-imap-connection")

    assert response.status_code == 200
    assert response.json()["connected"] is True


def test_hr_inbox_test_imap_connection_failure_reported_inline_not_502(client, db_session, monkeypatch):
    from app.integrations.imap_poll import ImapError

    _reset_hr_integration(db_session)
    client.put(
        "/hr-inbox/settings",
        json={
            "smtp_username": "hr@example.com", "smtp_password": "pw",
            "imap_host": "imap.example.com", "imap_port": 993, "use_ssl": True,
        },
    )
    monkeypatch.setattr(
        "app.hr_inbox.router.test_imap_connection",
        lambda hr_integration: (_ for _ in ()).throw(ImapError("Authentication failed")),
    )

    response = client.post("/hr-inbox/settings/test-imap-connection")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "Authentication failed" in body["detail"]


def test_hr_inbox_test_imap_connection_requires_admin_role(client, make_auth_headers):
    headers = make_auth_headers(role="recruiter", email="non-admin-test-imap@example.com")
    response = client.post("/hr-inbox/settings/test-imap-connection", headers=headers)
    assert response.status_code == 403
