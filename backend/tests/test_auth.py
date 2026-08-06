import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings


def test_register_creates_user(anonymous_client):
    response = anonymous_client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "supersecret123",
            "full_name": "New User",
            "role": "recruiter",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["full_name"] == "New User"
    assert body["role"] == "recruiter"
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_rejects_duplicate_email(anonymous_client):
    payload = {
        "email": "dupe@example.com",
        "password": "supersecret123",
        "full_name": "Dupe",
        "role": "recruiter",
    }

    first = anonymous_client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = anonymous_client.post("/auth/register", json=payload)
    assert second.status_code == 400


def test_register_rejects_invalid_role(anonymous_client):
    response = anonymous_client.post(
        "/auth/register",
        json={"email": "badrole@example.com", "password": "supersecret123", "role": "ceo"},
    )
    assert response.status_code == 422


def test_register_rejects_admin_role(anonymous_client):
    response = anonymous_client.post(
        "/auth/register",
        json={"email": "wannabe-admin@example.com", "password": "supersecret123", "role": "admin"},
    )
    assert response.status_code == 422


def test_login_returns_access_token(anonymous_client):
    anonymous_client.post(
        "/auth/register",
        json={
            "email": "login-test@example.com",
            "password": "supersecret123",
            "full_name": "Login Test",
            "role": "recruiter",
        },
    )

    response = anonymous_client.post(
        "/auth/login", json={"email": "login-test@example.com", "password": "supersecret123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_me_returns_current_user(anonymous_client):
    anonymous_client.post(
        "/auth/register",
        json={
            "email": "me-test@example.com",
            "password": "supersecret123",
            "full_name": "Me Test",
            "role": "hiring_manager",
        },
    )
    login_response = anonymous_client.post(
        "/auth/login", json={"email": "me-test@example.com", "password": "supersecret123"}
    )
    token = login_response.json()["access_token"]

    response = anonymous_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me-test@example.com"
    assert body["full_name"] == "Me Test"
    assert body["role"] == "hiring_manager"


def test_me_rejects_missing_token(anonymous_client):
    response = anonymous_client.get("/auth/me")
    assert response.status_code == 401


def test_login_rejects_wrong_password(anonymous_client):
    anonymous_client.post(
        "/auth/register",
        json={
            "email": "wrongpw@example.com",
            "password": "supersecret123",
            "full_name": "Wrong Password",
            "role": "recruiter",
        },
    )

    response = anonymous_client.post(
        "/auth/login", json={"email": "wrongpw@example.com", "password": "incorrect-password"}
    )

    assert response.status_code == 401


def test_login_rejects_unknown_email(anonymous_client):
    response = anonymous_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


def test_protected_route_rejects_missing_token(anonymous_client):
    response = anonymous_client.get("/jobs")
    assert response.status_code == 401


def test_protected_route_rejects_invalid_token(anonymous_client):
    response = anonymous_client.get("/jobs", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_protected_route_rejects_expired_token(anonymous_client):
    expired_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = anonymous_client.get("/jobs", headers={"Authorization": f"Bearer {expired_token}"})

    assert response.status_code == 401


def test_token_with_malformed_sub_claim_is_rejected(anonymous_client):
    # A token can decode successfully but carry a `sub` that isn't a valid UUID at all
    # (e.g. a forged/tampered token) -- this must be a clean 401, not a raw 500.
    malformed_token = jwt.encode(
        {"sub": "not-a-uuid", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = anonymous_client.get("/jobs", headers={"Authorization": f"Bearer {malformed_token}"})

    assert response.status_code == 401


def test_valid_token_for_deleted_user_is_rejected(anonymous_client, make_auth_headers):
    # A token can decode successfully but still be invalid if the user no longer
    # exists (e.g. deleted after the token was issued).
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = anonymous_client.get("/jobs", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_role_mismatch_rejected_for_job_creation(anonymous_client, make_auth_headers):
    headers = make_auth_headers(role="interviewer", email="interviewer@example.com")

    response = anonymous_client.post(
        "/jobs", json={"title": "Should Not Be Created"}, headers=headers
    )

    assert response.status_code == 403


def test_matching_role_allows_job_creation(anonymous_client, make_auth_headers):
    headers = make_auth_headers(role="recruiter", email="recruiter-can-create@example.com")

    response = anonymous_client.post(
        "/jobs", json={"title": "Allowed Job"}, headers=headers
    )

    assert response.status_code == 201
