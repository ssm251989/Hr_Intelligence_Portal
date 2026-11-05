"""platform/iam/mfa.py -- TOTP enrollment/verification, recovery codes, email-OTP
challenges (Part 5A CHECKS, spec's own "every role blocked until 2FA enrolled" scenario,
exercised directly against the mechanism rather than retrofitted onto the shared `client`
fixture's admin user -- see docs/build_log.md's own Part 5 note on why iam.auth.
mfa_required defaults false platform-wide)."""

import uuid

import pyotp
import pytest

from app.core.security import hash_password
from app.models.iam import MfaRecoveryCode
from app.models.user import User
from app.platform.iam import mfa
from app.platform.settings.resolver import SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session) -> User:
    user = User(email=f"mfa-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_mfa_required_defaults_false_platform_wide(db_session):
    assert mfa.is_mfa_required(db_session, TENANT) is False


def test_mfa_required_can_be_turned_on_via_settings(db_session):
    SettingsService(db_session).set("iam.auth.mfa_required", True, scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    assert mfa.is_mfa_required(db_session, TENANT) is True


def test_user_is_not_enrolled_by_default(db_session):
    user = _make_user(db_session)
    assert mfa.is_mfa_enrolled(user) is False


def test_totp_enrollment_flow_start_confirm_verify(db_session):
    user = _make_user(db_session)
    secret, uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    assert uri.startswith("otpauth://totp/")
    assert mfa.is_mfa_enrolled(user) is False  # not yet confirmed

    code = pyotp.totp.TOTP(secret).now()
    recovery_codes = mfa.confirm_totp_enrollment(db_session, TENANT, user, code)

    assert len(recovery_codes) == mfa.RECOVERY_CODE_COUNT
    assert mfa.is_mfa_enrolled(user) is True
    assert mfa.verify_totp_code(db_session, TENANT, user, pyotp.totp.TOTP(secret).now()) is True


def test_confirm_totp_enrollment_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    mfa.start_totp_enrollment(db_session, TENANT, user)
    with pytest.raises(ValueError):
        mfa.confirm_totp_enrollment(db_session, TENANT, user, "000000")
    assert mfa.is_mfa_enrolled(user) is False


def test_confirm_totp_enrollment_without_start_raises(db_session):
    user = _make_user(db_session)
    with pytest.raises(ValueError):
        mfa.confirm_totp_enrollment(db_session, TENANT, user, "123456")


def test_totp_secret_is_never_stored_in_plaintext_on_the_user_row(db_session):
    user = _make_user(db_session)
    secret, _uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    assert user.mfa_totp_secret_ref != secret
    assert secret not in (user.mfa_totp_secret_ref or "")


def test_recovery_code_works_once_then_is_rejected(db_session):
    user = _make_user(db_session)
    secret, _uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    recovery_codes = mfa.confirm_totp_enrollment(db_session, TENANT, user, pyotp.totp.TOTP(secret).now())

    code = recovery_codes[0]
    assert mfa.verify_recovery_code(db_session, TENANT, user, code) is True
    assert mfa.verify_recovery_code(db_session, TENANT, user, code) is False


def test_disable_totp_clears_enrollment_and_recovery_codes(db_session):
    user = _make_user(db_session)
    secret, _uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    mfa.confirm_totp_enrollment(db_session, TENANT, user, pyotp.totp.TOTP(secret).now())

    mfa.disable_totp(db_session, TENANT, user)

    assert mfa.is_mfa_enrolled(user) is False
    assert db_session.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).count() == 0


def test_totp_login_challenge_succeeds_with_correct_code_and_consumes_itself(db_session):
    user = _make_user(db_session)
    secret, _uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    mfa.confirm_totp_enrollment(db_session, TENANT, user, pyotp.totp.TOTP(secret).now())

    challenge = mfa.create_totp_challenge(db_session, TENANT, user)
    verified = mfa.verify_challenge(db_session, TENANT, challenge.id, pyotp.totp.TOTP(secret).now())
    assert verified is not None
    assert verified.id == user.id

    # the same challenge cannot be replayed
    assert mfa.verify_challenge(db_session, TENANT, challenge.id, pyotp.totp.TOTP(secret).now()) is None


def test_totp_login_challenge_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    secret, _uri = mfa.start_totp_enrollment(db_session, TENANT, user)
    mfa.confirm_totp_enrollment(db_session, TENANT, user, pyotp.totp.TOTP(secret).now())

    challenge = mfa.create_totp_challenge(db_session, TENANT, user)
    assert mfa.verify_challenge(db_session, TENANT, challenge.id, "000000") is None


def test_email_otp_challenge_succeeds_with_the_generated_code(db_session):
    user = _make_user(db_session)
    challenge, plaintext_code = mfa.create_email_otp_challenge(db_session, TENANT, user)
    assert len(plaintext_code) == mfa.EMAIL_OTP_LENGTH

    verified = mfa.verify_challenge(db_session, TENANT, challenge.id, plaintext_code)
    assert verified is not None and verified.id == user.id


def test_email_otp_challenge_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    challenge, _code = mfa.create_email_otp_challenge(db_session, TENANT, user)
    assert mfa.verify_challenge(db_session, TENANT, challenge.id, "000000") is None


def test_challenge_locks_out_after_max_attempts(db_session):
    user = _make_user(db_session)
    challenge, code = mfa.create_email_otp_challenge(db_session, TENANT, user)

    for _ in range(mfa.MAX_CHALLENGE_ATTEMPTS):
        mfa.verify_challenge(db_session, TENANT, challenge.id, "000000")

    # even the correct code no longer works once attempts are exhausted
    assert mfa.verify_challenge(db_session, TENANT, challenge.id, code) is None
