"""Part 20.1 / 20.2: the employee's HR Automation app account.

Login = the company email (personal email only while there is no company email). The account is created
with an unusable random password; the person gets a "Set your password" link (72 hours, single use) at
their company email, with the personal email as a backup. Nothing secret is ever emailed or stored.
"""

import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Employee
from app.models.user import User

INVITE_HOURS = 72


def login_email(e: Employee) -> Optional[str]:
    return (e.company_email or e.personal_email or "").strip().lower() or None


def ensure_account(db: Session, tenant, e: Employee, *, actor: str, extra_roles: Optional[list[str]] = None) -> User:
    """The employee's user (created when missing; never a second one). Role Employee + any extra roles."""
    from app.core.security import hash_password
    from app.employees.roles import add_roles
    from app.platform.iam.roles import bridge_single_user

    user = db.get(User, e.user_id) if e.user_id else None
    email = login_email(e)
    if user is None and email:
        user = db.query(User).filter(User.email == email).first()
    if user is None:
        if not email:
            raise ValueError("This employee has no company or personal email, so an app account can't be created.")
        name = " ".join(p for p in (e.first_name, e.last_name) if p)
        user = User(tenant_id=tenant.tenant_id, email=email, full_name=name or email, role="employee",
                    hashed_password=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.commit()
        db.refresh(user)
        bridge_single_user(db, tenant, user)
        log_action(db, "user", user.id, "employee_account_created", actor[:50], {"employee_id": str(e.id), "login": email})
    elif e.company_email and user.email != e.company_email.lower() and user.password_set_at is None:
        # not used yet: move the login to the company email
        if db.query(User.id).filter(User.email == e.company_email.lower(), User.id != user.id).first() is None:
            user.email = e.company_email.lower()
            db.commit()
    if e.user_id != user.id:
        e.user_id = user.id
        db.commit()
    add_roles(db, tenant, user, ["Employee", *(extra_roles or [])])
    return user


def invite_link(db: Session, tenant, user: User, *, actor: str) -> str:
    from app.core.config import settings as app_settings
    from app.platform.iam.action_tokens import create_action_token

    token = create_action_token(db, tenant, entity_type="user", entity_id=user.id, action="set_password", created_by=actor[:50],
                                ttl_days=INVITE_HOURS // 24).token
    return f"{app_settings.FRONTEND_URL.rstrip('/')}/set-password?token={token}"


def send_invite(db: Session, tenant, e: Employee, *, actor: str) -> dict:
    """Creates the account if needed and emails the set-password link (company email + personal backup)."""
    from app.platform.comms.defaults import send_default

    user = ensure_account(db, tenant, e, actor=actor)
    if user.deactivated_at is not None:
        raise ValueError("This app account is switched off. Switch it on in Settings > People & access first.")
    link = invite_link(db, tenant, user, actor=actor)
    to = [a for a in dict.fromkeys([user.email, (e.personal_email or "").lower()]) if a]
    status = None
    try:
        m = send_default(db, tenant, "employee.app_invite", to=to, purpose="email.outbound.system", related_entity_type="employee",
                         related_entity_id=e.id, ctx={"first_name": e.preferred_name or e.first_name, "link": link, "login": user.email,
                                                      "hours": str(INVITE_HOURS)})
        status = m.status
    except Exception as exc:  # noqa: BLE001 -- shown to HR in plain words, never silent
        status = f"failed: {str(exc)[:120]}"
    log_action(db, "employee", e.id, "app_invite_sent", actor[:50], {"to": to, "email": status})
    return {"user_id": str(user.id), "login": user.email, "sent_to": to, "email_status": status,
            "link": link if status and status.startswith("failed") else None}
