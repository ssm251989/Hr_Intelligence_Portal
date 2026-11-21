"""L1 / L2 / L3 (Part 27): forgot password, the locked-account message, public sign-up closed."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password, verify_password
from app.models.iam import ActionToken
from app.models.audit_log import AuditLog
from app.models.user import User


@pytest.fixture()
def mailbox(monkeypatch):
    """Forgot password needs a connected mailbox; the email itself is captured."""
    sent = []

    class _Msg:
        status = "sent"

    monkeypatch.setattr("app.auth.router._email_reset_available", lambda db, tenant: True)
    monkeypatch.setattr("app.platform.comms.defaults.send_default", lambda db, tenant, key, **k: sent.append((key, k)) or _Msg())
    return sent


def _user(db, password="Old pass 123!", **kw):
    u = User(email=f"fp-{uuid.uuid4().hex[:6]}@example.com", hashed_password=hash_password(password), full_name="Fiona P", role="recruiter",
             password_set_at=datetime.now(timezone.utc), **kw)
    db.add(u)
    db.commit()
    return u


def _token(db, user):
    return db.query(ActionToken).filter(ActionToken.entity_id == user.id, ActionToken.action == "set_password").order_by(ActionToken.created_at.desc()).first()


def test_same_answer_whether_the_email_exists_or_not(anonymous_client, db_session, mailbox):
    u = _user(db_session)
    known = anonymous_client.post("/auth/forgot-password", json={"email": u.email.upper()})
    unknown = anonymous_client.post("/auth/forgot-password", json={"email": "nobody-here@example.com"})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()
    assert [k for k, _ in mailbox] == ["platform.password_forgot"]  # only the real account got an email
    row = _token(db_session, u)
    assert timedelta(minutes=29) < row.expires_at - datetime.now(timezone.utc) <= timedelta(minutes=30)
    assert db_session.query(AuditLog).filter(AuditLog.action == "password_reset_requested").count() >= 2


def test_reset_link_works_once_and_follows_the_password_rules(anonymous_client, db_session, mailbox):
    u = _user(db_session, password="Old pass 123!")
    anonymous_client.post("/auth/forgot-password", json={"email": u.email})
    token = _token(db_session, u).token
    short = anonymous_client.post("/auth/set-password", json={"token": token, "password": "abc"})
    assert short.status_code == 400 and "at least" in short.json()["detail"]
    reused = anonymous_client.post("/auth/set-password", json={"token": token, "password": "Old pass 123!"})
    assert reused.status_code == 400 and "haven't used before" in reused.json()["detail"]
    ok = anonymous_client.post("/auth/set-password", json={"token": token, "password": "Brand new 456!"})
    assert ok.status_code == 204
    db_session.refresh(u)
    assert verify_password("Brand new 456!", u.hashed_password)
    again = anonymous_client.post("/auth/set-password", json={"token": token, "password": "Another 789!"})
    assert again.status_code == 400  # single use


def test_forgot_password_is_rate_limited(anonymous_client, db_session, mailbox):
    email = f"rl-{uuid.uuid4().hex[:6]}@example.com"
    codes = [anonymous_client.post("/auth/forgot-password", json={"email": email}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_without_a_mailbox_the_page_says_ask_your_admin(anonymous_client, monkeypatch):
    monkeypatch.setattr("app.auth.router._email_reset_available", lambda db, tenant: False)
    assert anonymous_client.get("/auth/forgot-password").json() == {"email_reset": False}


def test_locked_account_says_how_many_minutes(anonymous_client, db_session):
    u = _user(db_session, password="Right pass 1!", locked_until=datetime.now(timezone.utc) + timedelta(minutes=14, seconds=30))
    r = anonymous_client.post("/auth/login", json={"email": u.email, "password": "Right pass 1!"})
    assert r.status_code == 423 and r.json()["detail"] == "Too many attempts - try again in 15 minutes."


@pytest.mark.signup_closed
def test_public_sign_up_is_closed(anonymous_client):
    r = anonymous_client.post("/auth/register", json={"email": "walk-in@example.com", "password": "supersecret123", "full_name": "W", "role": "recruiter"})
    assert r.status_code == 404
