"""Sessions (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 1): rotating refresh tokens,
device list/revoke, login lockout, and the per-tenant IP allow-list setting's actual
enforcement. Only a refresh token's SHA-256 hash is ever stored -- same principle as a
password hash (a DB read alone can never mint a session)."""

import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.iam import RefreshToken, UserDevice
from app.models.user import User
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_or_create_device(db: Session, tenant: TenantContext, user: User, *, user_agent: Optional[str], ip_address: Optional[str]) -> UserDevice:
    device = UserDevice(
        tenant_id=tenant.tenant_id, user_id=user.id, user_agent=user_agent, ip_address=ip_address,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def remember_device(db: Session, tenant: TenantContext, device: UserDevice) -> None:
    days = int(SettingsService(db).get("iam.auth.remember_device_days", SettingContext(tenant=tenant)) or 30)
    device.mfa_remembered_until = datetime.now(timezone.utc) + timedelta(days=days)
    db.commit()


def is_device_mfa_remembered(device: Optional[UserDevice]) -> bool:
    return device is not None and device.revoked_at is None and device.mfa_remembered_until is not None and device.mfa_remembered_until > datetime.now(timezone.utc)


def issue_refresh_token(db: Session, tenant: TenantContext, user: User, device: Optional[UserDevice] = None) -> tuple[str, RefreshToken]:
    days = int(SettingsService(db).get("iam.auth.refresh_token_expiry_days", SettingContext(tenant=tenant)) or 30)
    plaintext = secrets.token_urlsafe(48)
    row = RefreshToken(
        tenant_id=tenant.tenant_id, user_id=user.id, device_id=device.id if device else None,
        token_hash=_hash_token(plaintext), expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return plaintext, row


class InvalidRefreshTokenError(Exception):
    pass


def rotate_refresh_token(db: Session, tenant: TenantContext, plaintext: str) -> tuple[str, RefreshToken, User]:
    """Consumes `plaintext` (marks it revoked + linked to its replacement) and issues a
    new one -- reuse of an already-rotated token is refused (a classic rotating-refresh-
    token compromise signal), not silently accepted."""
    existing = (
        db.query(RefreshToken)
        .filter(RefreshToken.tenant_id == tenant.tenant_id, RefreshToken.token_hash == _hash_token(plaintext))
        .first()
    )
    if existing is None or existing.revoked_at is not None or existing.expires_at < datetime.now(timezone.utc):
        raise InvalidRefreshTokenError("Refresh token is invalid, expired, or already used")

    user = db.get(User, existing.user_id)
    if user is None:
        raise InvalidRefreshTokenError("Refresh token's user no longer exists")

    device = db.get(UserDevice, existing.device_id) if existing.device_id else None
    new_plaintext, new_row = issue_refresh_token(db, tenant, user, device)
    existing.revoked_at = datetime.now(timezone.utc)
    existing.replaced_by_id = new_row.id
    db.commit()
    return new_plaintext, new_row, user


def revoke_refresh_token_by_id(db: Session, tenant: TenantContext, token_id: UUID) -> None:
    row = db.get(RefreshToken, token_id)
    if row is not None and row.tenant_id == tenant.tenant_id:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


def list_devices(db: Session, tenant: TenantContext, user: User) -> list[UserDevice]:
    return (
        db.query(UserDevice)
        .filter(UserDevice.tenant_id == tenant.tenant_id, UserDevice.user_id == user.id, UserDevice.revoked_at.is_(None))
        .order_by(UserDevice.last_seen_at.desc())
        .all()
    )


def revoke_device(db: Session, tenant: TenantContext, device_id: UUID) -> None:
    """Revokes the device AND every refresh token ever issued against it -- a stolen
    device's session must not survive just because its own refresh token hasn't expired
    yet."""
    device = db.get(UserDevice, device_id)
    if device is None or device.tenant_id != tenant.tenant_id:
        return
    device.revoked_at = datetime.now(timezone.utc)
    db.query(RefreshToken).filter(
        RefreshToken.tenant_id == tenant.tenant_id, RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})
    db.commit()


# ---- lockout ----


def is_locked_out(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > datetime.now(timezone.utc)


def record_failed_login(db: Session, tenant: TenantContext, user: User) -> None:
    threshold = int(SettingsService(db).get("iam.auth.lockout_threshold", SettingContext(tenant=tenant)) or 5)
    duration = int(SettingsService(db).get("iam.auth.lockout_duration_minutes", SettingContext(tenant=tenant)) or 15)
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= threshold:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=duration)
    db.commit()


def reset_failed_logins(db: Session, user: User) -> None:
    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


# ---- IP allow-list ----


def is_ip_allowed(db: Session, tenant: TenantContext, ip_address: Optional[str]) -> bool:
    """The setting default is `[]` (unrestricted) -- an empty allow-list means every IP is
    allowed, not zero, matching how every other new iam.auth.* setting in this part
    defaults to "don't change current behavior" (see bootstrap_definitions.py's own
    comment on why mfa_required defaults false)."""
    allowlist = SettingsService(db).get("iam.auth.ip_allowlist", SettingContext(tenant=tenant)) or []
    if not allowlist:
        return True
    if not ip_address:
        return False
    try:
        candidate = ipaddress.ip_address(ip_address)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if "/" in entry:
                if candidate in ipaddress.ip_network(entry, strict=False):
                    return True
            elif candidate == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False
