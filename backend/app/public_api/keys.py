"""Part 30.2a: API keys. The key is shown once ("hra_live_<prefix><secret>" / "hra_test_..."); only its SHA-256 is
kept. A key belongs to one company (RLS) and acts as the person who created it: their permissions apply to every
call, so a key never does more than its creator could do on the screens.

Test mode: "hra_test_" keys exist only on a sandbox company (slug "sandbox" or "<company>-sandbox", made with
`python -m hrctl.tenant create --slug sandbox ...`), whose mail goes to Mailpit; live keys never work there and a
test key never works on a live company.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.public_api import SCOPES, ApiKey
from app.models.user import User

PREFIX = {"live": "hra_live_", "test": "hra_test_"}
PERMISSION = "platform.api_keys.manage"


class KeyError_(ValueError):
    """A key the API refuses: code + plain message (401/403 in the router)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def is_sandbox(tenant) -> bool:
    slug = (getattr(tenant, "slug", "") or "").lower()
    return slug == "sandbox" or slug.endswith("-sandbox")


def mode_for(tenant) -> str:
    return "test" if is_sandbox(tenant) else "live"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(db: Session, tenant, user: User, *, name: str, scopes: list[str], expires_at: Optional[datetime] = None) -> tuple[ApiKey, str]:
    """Returns (row, the full key). The full key is never stored and never shown again."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the key a name (e.g. the system that will use it).")
    bad = [s for s in scopes if s not in SCOPES]
    if bad or not scopes:
        raise ValueError(f"Choose at least one scope from: {', '.join(SCOPES)}." + (f" Unknown: {', '.join(bad)}." if bad else ""))
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise ValueError("The expiry date must be in the future.")
    mode = mode_for(tenant)
    public = secrets.token_hex(4)  # 8 chars, shown in the list
    full = f"{PREFIX[mode]}{public}{secrets.token_urlsafe(30)}"
    row = ApiKey(tenant_id=tenant.tenant_id, name=name[:100], prefix=f"{PREFIX[mode]}{public}", secret_hash=_hash(full),
                 scopes=sorted(set(scopes)), mode=mode, created_by=user.id, expires_at=expires_at)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, full


def revoke(db: Session, row: ApiKey) -> ApiKey:
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return row


def authenticate(db: Session, tenant, raw: Optional[str]) -> tuple[ApiKey, User]:
    """`Authorization: Bearer <key>` -> (key, the person it acts as). Raises KeyError_ with a plain reason."""
    raw = (raw or "").strip()
    if not raw:
        raise KeyError_(401, "missing_key", "Send your API key as 'Authorization: Bearer <key>'.")
    mode = next((m for m, p in PREFIX.items() if raw.startswith(p)), None)
    if mode is None or len(raw) < len(PREFIX[mode]) + 9:
        raise KeyError_(401, "invalid_key", "This is not an HR Automation API key.")
    if mode != mode_for(tenant):
        raise KeyError_(403, "wrong_mode", "Test keys (hra_test_) work only on the sandbox company; live keys never do."
                        if mode == "test" else "Live keys (hra_live_) never work on the sandbox company - use a test key there.")
    prefix = raw[:len(PREFIX[mode]) + 8]
    row = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.tenant_id, ApiKey.prefix == prefix).first()
    if row is None or not secrets.compare_digest(row.secret_hash, _hash(raw)):
        raise KeyError_(401, "invalid_key", "This API key is not valid for this company.")
    now = datetime.now(timezone.utc)
    if row.revoked_at is not None:
        raise KeyError_(401, "revoked_key", "This API key was revoked. Create a new one on Settings > Developers.")
    if row.expires_at is not None and row.expires_at <= now:
        raise KeyError_(401, "expired_key", "This API key has expired. Create a new one on Settings > Developers.")
    user = db.get(User, row.created_by)
    if user is None or getattr(user, "deactivated_at", None) is not None:
        raise KeyError_(401, "owner_inactive", "The person who created this key can no longer sign in, so the key stopped working.")
    row.last_used_at = now
    db.commit()
    return row, user


def to_dict(row: ApiKey) -> dict:
    return {"id": str(row.id), "name": row.name, "prefix": row.prefix, "scopes": row.scopes or [], "mode": row.mode,
            "created_by": str(row.created_by), "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None}
