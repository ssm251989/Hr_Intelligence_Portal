"""auth/router.py's rewritten login() (Part 5A): password + optional 2FA step, refresh
token rotation, session/device list+revoke, lockout, MFA self-service enrollment -- all
exercised over real HTTP (anonymous_client goes through the full middleware stack, so
tenant context resolves the same way a real request's does, unlike the `client` fixture's
own direct create_access_token shortcut)."""

import pyotp

from app.platform.settings.resolver import SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _register(anonymous_client, email="login-flow@example.com", password="supersecret123"):
    response = anonymous_client.post("/auth/register", json={"email": email, "password": password, "full_name": "T", "role": "recruiter"})
    assert response.status_code == 201
    return response.json()


def test_login_without_mfa_required_returns_a_full_session_and_refresh_token(anonymous_client):
    _register(anonymous_client, email="a1@example.com")
    response = anonymous_client.post("/auth/login", json={"email": "a1@example.com", "password": "supersecret123"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["mfa_required"] is False


def test_login_with_wrong_password_returns_401(anonymous_client):
    _register(anonymous_client, email="a2@example.com")
    response = anonymous_client.post("/auth/login", json={"email": "a2@example.com", "password": "wrong-password"})
    assert response.status_code == 401


def test_repeated_failed_logins_lock_the_account(anonymous_client, db_session):
    _register(anonymous_client, email="a3@example.com")
    for _ in range(5):
        anonymous_client.post("/auth/login", json={"email": "a3@example.com", "password": "wrong-password"})

    response = anonymous_client.post("/auth/login", json={"email": "a3@example.com", "password": "supersecret123"})
    assert response.status_code == 423


def test_refresh_token_rotation_over_http(anonymous_client):
    _register(anonymous_client, email="a4@example.com")
    login = anonymous_client.post("/auth/login", json={"email": "a4@example.com", "password": "supersecret123"}).json()

    refreshed = anonymous_client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    new_body = refreshed.json()
    assert new_body["refresh_token"] != login["refresh_token"]

    # the old refresh token is now dead
    reused = anonymous_client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert reused.status_code == 401


def test_logout_revokes_the_refresh_token(anonymous_client):
    _register(anonymous_client, email="a5@example.com")
    login = anonymous_client.post("/auth/login", json={"email": "a5@example.com", "password": "supersecret123"}).json()

    logout_response = anonymous_client.post("/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert logout_response.status_code == 204

    reused = anonymous_client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert reused.status_code == 401


def test_sessions_list_and_revoke(anonymous_client):
    _register(anonymous_client, email="a6@example.com")
    login = anonymous_client.post("/auth/login", json={"email": "a6@example.com", "password": "supersecret123"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    listed = anonymous_client.get("/auth/sessions", headers=headers)
    assert listed.status_code == 200
    devices = listed.json()
    assert len(devices) == 1
    assert devices[0]["id"] == login["device_id"]

    revoked = anonymous_client.delete(f"/auth/sessions/{login['device_id']}", headers=headers)
    assert revoked.status_code == 204

    listed_again = anonymous_client.get("/auth/sessions", headers=headers)
    assert listed_again.json() == []


def test_mfa_enrollment_and_challenge_login_flow(anonymous_client, db_session):
    _register(anonymous_client, email="a7@example.com")
    login = anonymous_client.post("/auth/login", json={"email": "a7@example.com", "password": "supersecret123"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    started = anonymous_client.post("/auth/mfa/enroll/totp/start", headers=headers)
    assert started.status_code == 200
    secret = started.json()["secret"]

    confirmed = anonymous_client.post("/auth/mfa/enroll/totp/confirm", json={"code": pyotp.totp.TOTP(secret).now()}, headers=headers)
    assert confirmed.status_code == 200
    assert len(confirmed.json()["recovery_codes"]) == 10

    SettingsService(db_session).set("iam.auth.mfa_required", True, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)

    challenge_response = anonymous_client.post("/auth/login", json={"email": "a7@example.com", "password": "supersecret123"})
    assert challenge_response.status_code == 200
    challenge_body = challenge_response.json()
    assert challenge_body["mfa_required"] is True
    assert challenge_body["mfa_methods"] == ["totp"]
    assert challenge_body["access_token"] is None

    verified = anonymous_client.post("/auth/mfa/verify", json={"challenge_id": challenge_body["mfa_challenge_id"], "code": pyotp.totp.TOTP(secret).now()})
    assert verified.status_code == 200
    assert verified.json()["access_token"]

    SettingsService(db_session).set("iam.auth.mfa_required", False, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)


def test_mfa_required_but_not_enrolled_forces_enrollment_before_a_real_session(anonymous_client, db_session):
    _register(anonymous_client, email="a8@example.com")
    SettingsService(db_session).set("iam.auth.mfa_required", True, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)

    response = anonymous_client.post("/auth/login", json={"email": "a8@example.com", "password": "supersecret123"})
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_enrollment_required"] is True
    assert body["access_token"] is None
    assert body["mfa_enrollment_token"]

    # the enrollment token works for enroll endpoints...
    headers = {"Authorization": f"Bearer {body['mfa_enrollment_token']}"}
    started = anonymous_client.post("/auth/mfa/enroll/totp/start", headers=headers)
    assert started.status_code == 200

    # ...but NOT as a general session token
    me = anonymous_client.get("/auth/me", headers=headers)
    assert me.status_code == 401

    SettingsService(db_session).set("iam.auth.mfa_required", False, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)


def test_wrong_mfa_challenge_code_is_rejected(anonymous_client, db_session):
    _register(anonymous_client, email="a9@example.com")
    login = anonymous_client.post("/auth/login", json={"email": "a9@example.com", "password": "supersecret123"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    started = anonymous_client.post("/auth/mfa/enroll/totp/start", headers=headers).json()
    anonymous_client.post("/auth/mfa/enroll/totp/confirm", json={"code": pyotp.totp.TOTP(started["secret"]).now()}, headers=headers)

    SettingsService(db_session).set("iam.auth.mfa_required", True, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    challenge_body = anonymous_client.post("/auth/login", json={"email": "a9@example.com", "password": "supersecret123"}).json()

    wrong = anonymous_client.post("/auth/mfa/verify", json={"challenge_id": challenge_body["mfa_challenge_id"], "code": "000000"})
    assert wrong.status_code == 401

    SettingsService(db_session).set("iam.auth.mfa_required", False, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
