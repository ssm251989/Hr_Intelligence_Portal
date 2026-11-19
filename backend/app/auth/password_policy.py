"""The company's password rules (Settings > Security: iam.auth.*), in one place (L1, Part 27).

Used whenever a person chooses a password through a link (invite / reset / forgot password):
- iam.auth.password_min_length      at least N characters
- iam.auth.password_require_complexity  letters, digits and a symbol
- iam.auth.password_history_count   not one of the last N passwords (password_history + the current one)
"""

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.iam import PasswordHistory
from app.models.user import User


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def problems(db: Session, tenant, user: Optional[User], password: str) -> list[str]:
    """Everything wrong with the new password, in plain words (all at once)."""
    out = []
    min_length = int(_setting(db, tenant, "iam.auth.password_min_length") or 8)
    if len(password) < min_length:
        out.append(f"Password must be at least {min_length} characters")
    if password != password.strip() or any(c in password for c in "\r\n\t"):
        out.append("Password must not start or end with a space or contain line breaks or tabs")
    if _setting(db, tenant, "iam.auth.password_require_complexity"):
        if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password) and re.search(r"[^A-Za-z0-9]", password)):
            out.append("Password must have letters, numbers and a symbol")
    if user is not None:
        keep = int(_setting(db, tenant, "iam.auth.password_history_count") or 0)
        if keep > 0:
            recent = [user.hashed_password] + [h.hashed_password for h in db.query(PasswordHistory).filter(PasswordHistory.user_id == user.id)
                                                .order_by(PasswordHistory.created_at.desc()).limit(keep - 1)]
            if any(h and _same(password, h) for h in recent):
                out.append(f"Choose a password you haven't used before (the last {keep} can't be reused)")
    return out


def _same(password: str, hashed: str) -> bool:
    try:
        return verify_password(password, hashed)
    except Exception:  # noqa: BLE001 -- an unreadable old hash never blocks a new password
        return False


def remember_old(db: Session, tenant, user: User) -> None:
    """Keep the outgoing password's hash for the history rule (call before replacing it)."""
    if user.hashed_password:
        db.add(PasswordHistory(tenant_id=tenant.tenant_id if tenant else user.tenant_id, user_id=user.id, hashed_password=user.hashed_password))
