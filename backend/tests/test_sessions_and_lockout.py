"""platform/iam/sessions.py -- refresh token rotation, device list/revoke, login lockout,
IP allow-list (Part 5A CHECKS)."""

import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import hash_password
from app.models.iam import RefreshToken
from app.models.user import User
from app.platform.iam import sessions
from app.platform.settings.resolver import SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session) -> User:
    user = User(email=f"sess-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_issue_refresh_token_stores_only_the_hash(db_session):
    user = _make_user(db_session)
    plaintext, row = sessions.issue_refresh_token(db_session, TENANT, user)
    assert row.token_hash != plaintext
    assert plaintext not in row.token_hash


def test_rotate_refresh_token_issues_a_new_one_and_revokes_the_old(db_session):
    user = _make_user(db_session)
    plaintext, row = sessions.issue_refresh_token(db_session, TENANT, user)

    new_plaintext, new_row, rotated_user = sessions.rotate_refresh_token(db_session, TENANT, plaintext)

    assert rotated_user.id == user.id
    assert new_plaintext != plaintext
    db_session.refresh(row)
    assert row.revoked_at is not None
    assert row.replaced_by_id == new_row.id


def test_rotate_refresh_token_rejects_reuse_of_an_already_rotated_token(db_session):
    user = _make_user(db_session)
    plaintext, _row = sessions.issue_refresh_token(db_session, TENANT, user)
    sessions.rotate_refresh_token(db_session, TENANT, plaintext)

    try:
        sessions.rotate_refresh_token(db_session, TENANT, plaintext)
        assert False, "expected InvalidRefreshTokenError"
    except sessions.InvalidRefreshTokenError:
        pass


def test_rotate_refresh_token_rejects_unknown_token(db_session):
    try:
        sessions.rotate_refresh_token(db_session, TENANT, "not-a-real-token")
        assert False, "expected InvalidRefreshTokenError"
    except sessions.InvalidRefreshTokenError:
        pass


def test_rotate_refresh_token_rejects_expired_token(db_session):
    user = _make_user(db_session)
    plaintext, row = sessions.issue_refresh_token(db_session, TENANT, user)
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    try:
        sessions.rotate_refresh_token(db_session, TENANT, plaintext)
        assert False, "expected InvalidRefreshTokenError"
    except sessions.InvalidRefreshTokenError:
        pass


def test_list_devices_excludes_revoked(db_session):
    user = _make_user(db_session)
    device = sessions.get_or_create_device(db_session, TENANT, user, user_agent="pytest", ip_address="127.0.0.1")
    assert device in sessions.list_devices(db_session, TENANT, user)

    sessions.revoke_device(db_session, TENANT, device.id)
    assert device not in sessions.list_devices(db_session, TENANT, user)


def test_revoke_device_also_revokes_its_refresh_tokens(db_session):
    user = _make_user(db_session)
    device = sessions.get_or_create_device(db_session, TENANT, user, user_agent="pytest", ip_address="127.0.0.1")
    _plaintext, row = sessions.issue_refresh_token(db_session, TENANT, user, device)

    sessions.revoke_device(db_session, TENANT, device.id)

    db_session.refresh(row)
    assert row.revoked_at is not None


def test_remember_device_sets_a_future_mfa_remembered_until(db_session):
    user = _make_user(db_session)
    device = sessions.get_or_create_device(db_session, TENANT, user, user_agent="pytest", ip_address="127.0.0.1")
    assert sessions.is_device_mfa_remembered(device) is False

    sessions.remember_device(db_session, TENANT, device)
    assert sessions.is_device_mfa_remembered(device) is True


# ---- lockout ----


def test_failed_logins_below_threshold_do_not_lock(db_session):
    user = _make_user(db_session)
    for _ in range(3):
        sessions.record_failed_login(db_session, TENANT, user)
    assert sessions.is_locked_out(user) is False


def test_failed_logins_at_threshold_lock_the_account(db_session):
    user = _make_user(db_session)
    for _ in range(5):
        sessions.record_failed_login(db_session, TENANT, user)
    assert sessions.is_locked_out(user) is True


def test_reset_failed_logins_clears_lockout(db_session):
    user = _make_user(db_session)
    for _ in range(5):
        sessions.record_failed_login(db_session, TENANT, user)
    assert sessions.is_locked_out(user) is True

    sessions.reset_failed_logins(db_session, user)
    assert sessions.is_locked_out(user) is False
    assert user.failed_login_attempts == 0


# ---- IP allow-list ----


def test_ip_allowlist_unrestricted_by_default(db_session):
    assert sessions.is_ip_allowed(db_session, TENANT, "8.8.8.8") is True
    assert sessions.is_ip_allowed(db_session, TENANT, None) is True


def test_ip_allowlist_rejects_ip_outside_the_list(db_session):
    SettingsService(db_session).set("iam.auth.ip_allowlist", ["10.0.0.0/8"], scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    assert sessions.is_ip_allowed(db_session, TENANT, "8.8.8.8") is False
    assert sessions.is_ip_allowed(db_session, TENANT, None) is False


def test_ip_allowlist_accepts_ip_inside_a_cidr_range(db_session):
    SettingsService(db_session).set("iam.auth.ip_allowlist", ["10.0.0.0/8"], scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    assert sessions.is_ip_allowed(db_session, TENANT, "10.1.2.3") is True


def test_ip_allowlist_accepts_an_exact_ip_match(db_session):
    SettingsService(db_session).set("iam.auth.ip_allowlist", ["203.0.113.7"], scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    assert sessions.is_ip_allowed(db_session, TENANT, "203.0.113.7") is True
    assert sessions.is_ip_allowed(db_session, TENANT, "203.0.113.8") is False
