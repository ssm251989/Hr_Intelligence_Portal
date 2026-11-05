"""2-step verification (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 1) -- TOTP
(authenticator app) or email OTP, recovery codes, admin reset. TOTP secrets are stored
through platform.secrets (envelope-encrypted, never plaintext in the DB) the same way a
Connection's own secret_ref already is (Part 3) -- `users.mfa_totp_secret_ref` is a
secret_ref string, not the secret itself.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import pyotp
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.iam import MfaChallenge, MfaRecoveryCode
from app.models.secret import Secret, SecretScope
from app.models.user import User
from app.platform.secrets.store import SecretNotFoundError, get_secret_store
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

RECOVERY_CODE_COUNT = 10
EMAIL_OTP_LENGTH = 6
EMAIL_OTP_TTL_MINUTES = 10
TOTP_CHALLENGE_TTL_MINUTES = 10


def _secret_store(db: Session, tenant: TenantContext):
    return get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))


def is_available(db: Session, tenant: TenantContext) -> bool:
    """Part 18.1: the whole 2-step feature is off unless Settings > Advanced switches it on."""
    return bool(SettingsService(db).get("iam.auth.two_step_available", SettingContext(tenant=tenant)))


def is_mfa_required(db: Session, tenant: TenantContext) -> bool:
    if not is_available(db, tenant):
        return False
    return bool(SettingsService(db).get("iam.auth.mfa_required", SettingContext(tenant=tenant)))


def is_mfa_enrolled(user: User) -> bool:
    return user.mfa_totp_enrolled_at is not None or user.mfa_email_otp_enabled


# ---- TOTP enrollment ----


def start_totp_enrollment(db: Session, tenant: TenantContext, user: User, *, issuer: str = "HR Automation") -> tuple[str, str]:
    """Generates a fresh secret, stores it (unconfirmed -- mfa_totp_enrolled_at stays
    NULL until confirm_totp_enrollment succeeds), returns (secret, otpauth_provisioning_uri)
    for the frontend to render as a QR code or manual-entry string."""
    secret = pyotp.random_base32()
    ref = f"user-mfa-totp-{user.id}"
    store = _secret_store(db, tenant)
    try:
        store.rotate(ref, secret, created_by="mfa.enroll")
    except SecretNotFoundError:
        store.put(ref, secret, created_by="mfa.enroll")
    user.mfa_totp_secret_ref = ref
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)
    return secret, uri


def confirm_totp_enrollment(db: Session, tenant: TenantContext, user: User, code: str) -> list[str]:
    """Verifies the first real code from the authenticator app, flips
    mfa_totp_enrolled_at, and issues RECOVERY_CODE_COUNT one-time recovery codes --
    returned in plaintext exactly once (only the hash is ever stored, same principle as a
    password)."""
    if not user.mfa_totp_secret_ref:
        raise ValueError("No TOTP enrollment in progress -- call start_totp_enrollment first")
    secret = _secret_store(db, tenant).get(user.mfa_totp_secret_ref)
    if not pyotp.totp.TOTP(secret).verify(code, valid_window=1):
        raise ValueError("Incorrect code")

    user.mfa_totp_enrolled_at = datetime.now(timezone.utc)
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.tenant_id == tenant.tenant_id, MfaRecoveryCode.user_id == user.id).delete()
    plaintext_codes = [secrets.token_hex(5) for _ in range(RECOVERY_CODE_COUNT)]
    for code_value in plaintext_codes:
        db.add(MfaRecoveryCode(tenant_id=tenant.tenant_id, user_id=user.id, code_hash=hash_password(code_value)))
    db.commit()
    return plaintext_codes


def disable_totp(db: Session, tenant: TenantContext, user: User) -> None:
    """Admin reset (section 1's own "admin reset with audit" -- the audit log_action call
    is the API router's job, same pattern as every other admin action in this app)."""
    if user.mfa_totp_secret_ref:
        try:
            _secret_store(db, tenant).delete(user.mfa_totp_secret_ref)
        except SecretNotFoundError:
            pass
    user.mfa_totp_secret_ref = None
    user.mfa_totp_enrolled_at = None
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.tenant_id == tenant.tenant_id, MfaRecoveryCode.user_id == user.id).delete()
    db.commit()


# ---- login-time verification ----


def verify_totp_code(db: Session, tenant: TenantContext, user: User, code: str) -> bool:
    if not user.mfa_totp_secret_ref:
        return False
    try:
        secret = _secret_store(db, tenant).get(user.mfa_totp_secret_ref)
    except SecretNotFoundError:
        return False
    return pyotp.totp.TOTP(secret).verify(code, valid_window=1)


def verify_recovery_code(db: Session, tenant: TenantContext, user: User, code: str) -> bool:
    rows = (
        db.query(MfaRecoveryCode)
        .filter(MfaRecoveryCode.tenant_id == tenant.tenant_id, MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
        .all()
    )
    for row in rows:
        if verify_password(code, row.code_hash):
            row.used_at = datetime.now(timezone.utc)
            db.commit()
            return True
    return False


def create_totp_challenge(db: Session, tenant: TenantContext, user: User) -> MfaChallenge:
    challenge = MfaChallenge(
        tenant_id=tenant.tenant_id, user_id=user.id, method="totp",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=TOTP_CHALLENGE_TTL_MINUTES),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


def create_email_otp_challenge(db: Session, tenant: TenantContext, user: User) -> tuple[MfaChallenge, str]:
    """Returns (challenge, plaintext_code) -- the caller sends plaintext_code via
    comms.send() (system.otp template, already seeded by Part 4's hrctl.migrate_comms_
    templates) and only ever persists its hash below."""
    code = "".join(secrets.choice("0123456789") for _ in range(EMAIL_OTP_LENGTH))
    challenge = MfaChallenge(
        tenant_id=tenant.tenant_id, user_id=user.id, method="email_otp", code_hash=hash_password(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=EMAIL_OTP_TTL_MINUTES),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge, code


def send_email_otp_challenge(db: Session, tenant: TenantContext, user: User) -> MfaChallenge:
    """create_email_otp_challenge() + actually emailing it, via Part 4's comms.send() and
    its already-seeded system.otp template -- the one place this module talks to comms,
    kept separate from create_email_otp_challenge() itself so a test can exercise the
    challenge/verify mechanics without needing a working mail connection."""
    from app.platform.comms.service import send

    challenge, code = create_email_otp_challenge(db, tenant, user)
    send(
        db, tenant, template_key="system.otp", to=[user.email],
        ctx={"otp_code": code, "expiry_minutes": EMAIL_OTP_TTL_MINUTES}, purpose="email.outbound.system",
    )
    return challenge


MAX_CHALLENGE_ATTEMPTS = 5


def verify_challenge(db: Session, tenant: TenantContext, challenge_id, code: str) -> Optional[User]:
    """Returns the User on success, None on failure (wrong code, expired, already
    consumed, or too many attempts) -- never raises, so a caller can present one uniform
    "invalid or expired code" message regardless of which specific reason applied."""
    challenge = db.get(MfaChallenge, challenge_id)
    if challenge is None or challenge.tenant_id != tenant.tenant_id:
        return None
    if challenge.consumed_at is not None or challenge.expires_at < datetime.now(timezone.utc):
        return None
    if challenge.attempts >= MAX_CHALLENGE_ATTEMPTS:
        return None

    user = db.get(User, challenge.user_id)
    if user is None:
        return None

    if challenge.method == "totp":
        ok = verify_totp_code(db, tenant, user, code) or verify_recovery_code(db, tenant, user, code)
    elif challenge.method == "email_otp":
        ok = challenge.code_hash is not None and verify_password(code, challenge.code_hash)
    else:
        ok = False

    challenge.attempts += 1
    if not ok:
        db.commit()
        return None

    challenge.consumed_at = datetime.now(timezone.utc)
    db.commit()
    return user
