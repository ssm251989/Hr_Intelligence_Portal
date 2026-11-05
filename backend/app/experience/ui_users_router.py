"""Part 18.22: Settings > People & access > Users, and Settings > Company > Offices.

Users (admins only):
- GET   /api/v1/ui/users                        everyone with role, extra roles, active, 2-step, last change
- POST  /api/v1/ui/users/invite                 {email, full_name, role} -> set-password link emailed (or returned)
- PATCH /api/v1/ui/users/{id}                   {full_name?, role?}
- POST  /api/v1/ui/users/{id}/deactivate | /reactivate   (never yourself, never the last admin)
- POST  /api/v1/ui/users/{id}/reset-password    set-password link emailed (or returned)
Offices (admins only):
- GET   /api/v1/ui/locations ; POST ; PATCH /{id} ; DELETE /{id}   (lat/lng = map position)
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui", tags=["ui-users"])
ROLE = Literal["admin", "recruiter", "hiring_manager", "interviewer"]


def _admin(db, user):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, "platform.settings.configure"):
        raise HTTPException(status_code=403, detail="Only an admin can manage users and offices.")
    return tenant


def _user(db, tenant, user_id) -> User:
    u = db.query(User).filter(User.tenant_id == tenant.tenant_id, User.id == user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def _link(db, tenant, user: User, actor: str, days: int) -> str:
    from app.core.config import settings as app_settings
    from app.platform.iam.action_tokens import create_action_token

    token = create_action_token(db, tenant, entity_type="user", entity_id=user.id, action="set_password", created_by=actor[:50], ttl_days=days).token
    return f"{app_settings.FRONTEND_URL.rstrip('/')}/set-password?token={token}"


def _mail(db, tenant, key, user: User, ctx: dict) -> bool:
    from app.platform.comms.defaults import send_default

    try:
        m = send_default(db, tenant, key, to=[user.email], ctx={"name": user.full_name or user.email, **ctx}, purpose="email.outbound.system")
        return m.status in ("sent", "queued")
    except Exception:  # noqa: BLE001 -- the link is returned instead
        return False


@router.get("/users")
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.iam import Role, RoleAssignment

    tenant = _admin(db, current_user)
    roles = {r.id: r.name for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id)}
    extra: dict = {}
    for a in db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id):
        extra.setdefault(a.user_id, []).append(roles.get(a.role_id, "?"))
    rows = db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role != "agency").order_by(User.created_at).all()
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "roles": sorted(set(extra.get(u.id, []))),
             "active": u.deactivated_at is None, "two_step": bool(u.mfa_totp_enrolled_at or u.mfa_email_otp_enabled),
             "locked": bool(u.locked_until and u.locked_until > datetime.now(timezone.utc)), "is_me": u.id == current_user.id,
             "created_at": u.created_at.isoformat() if u.created_at else None} for u in rows]


class InviteIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: Optional[str] = Field(None, max_length=255)
    role: ROLE = "recruiter"


@router.post("/users/invite", status_code=201)
def invite(body: InviteIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.core.security import hash_password
    from app.platform.iam.roles import bridge_single_user

    tenant = _admin(db, current_user)
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="Someone with this email already has an account.")
    u = User(tenant_id=tenant.tenant_id, email=email, full_name=body.full_name or email, role=body.role, hashed_password=hash_password(secrets.token_urlsafe(32)))
    db.add(u)
    db.commit()
    bridge_single_user(db, tenant, u)
    link = _link(db, tenant, u, current_user.email, 7)
    sent = _mail(db, tenant, "platform.user_invite", u, {"link": link, "invited_by": current_user.full_name or current_user.email, "role": body.role.replace("_", " ")})
    log_action(db, "user", u.id, "user_invited", current_user.email[:50], {"role": body.role, "email_sent": sent})
    return {"id": str(u.id), "email_sent": sent, "link": None if sent else link}


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[ROLE] = None


def _admins_left(db, tenant, excluding) -> int:
    return db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin", User.deactivated_at.is_(None), User.id != excluding).count()


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.iam import RoleAssignment
    from app.platform.iam.roles import _FLAT_ROLE_BRIDGE, bridge_single_user, sync_system_roles

    tenant = _admin(db, current_user)
    u = _user(db, tenant, user_id)
    before = {"full_name": u.full_name, "role": u.role}
    if body.full_name is not None:
        u.full_name = body.full_name.strip() or u.full_name
    if body.role is not None and body.role != u.role:
        if u.role == "admin" and _admins_left(db, tenant, u.id) == 0:
            raise HTTPException(status_code=400, detail="This is the only admin. Make someone else an admin first.")
        old_role = sync_system_roles(db, tenant).get(_FLAT_ROLE_BRIDGE.get(u.role, ""))
        if old_role is not None:  # the old role's automatic assignment goes; extra roles stay
            db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == u.id,
                                            RoleAssignment.role_id == old_role.id, RoleAssignment.scope_type == "all").delete(synchronize_session=False)
        u.role = body.role
        db.commit()
        bridge_single_user(db, tenant, u)
    db.commit()
    log_action(db, "user", u.id, "user_updated", current_user.email[:50], {"before": before, "after": {"full_name": u.full_name, "role": u.role}})
    return {"id": str(u.id), "full_name": u.full_name, "role": u.role}


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    u = _user(db, tenant, user_id)
    if u.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't switch off your own account.")
    if u.role == "admin" and _admins_left(db, tenant, u.id) == 0:
        raise HTTPException(status_code=400, detail="This is the only admin. Make someone else an admin first.")
    u.deactivated_at = datetime.now(timezone.utc)
    db.commit()
    log_action(db, "user", u.id, "user_deactivated", current_user.email[:50], {})
    return {"id": str(u.id), "active": False}


@router.post("/users/{user_id}/reactivate")
def reactivate(user_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    u = _user(db, tenant, user_id)
    u.deactivated_at = None
    u.failed_login_attempts, u.locked_until = 0, None
    db.commit()
    log_action(db, "user", u.id, "user_reactivated", current_user.email[:50], {})
    return {"id": str(u.id), "active": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    u = _user(db, tenant, user_id)
    link = _link(db, tenant, u, current_user.email, 2)
    sent = _mail(db, tenant, "platform.password_reset_link", u, {"link": link})
    u.failed_login_attempts, u.locked_until = 0, None
    db.commit()
    log_action(db, "user", u.id, "user_password_reset_sent", current_user.email[:50], {"email_sent": sent})
    return {"email_sent": sent, "link": None if sent else link}


# ---------------------------------------------------------------- offices

class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address: Optional[str] = Field(None, max_length=1000)
    state: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=50)
    geo_lat: Optional[float] = Field(None, ge=-90, le=90)
    geo_lng: Optional[float] = Field(None, ge=-180, le=180)
    legal_entity_id: Optional[uuid.UUID] = None


def _loc_row(l) -> dict:
    return {"id": str(l.id), "name": l.name, "address": l.address, "state": l.state, "timezone": l.timezone, "geo_lat": l.geo_lat, "geo_lng": l.geo_lng,
            "legal_entity_id": str(l.legal_entity_id) if l.legal_entity_id else None}


@router.get("/locations")
def locations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import LegalEntity, Location

    tenant = _admin(db, current_user)
    return {"locations": [_loc_row(l) for l in db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name)],
            "entities": [{"id": str(e.id), "name": e.name} for e in db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id).order_by(LegalEntity.name)]}


def _apply(l, body: LocationIn):
    l.name, l.address, l.state = body.name.strip(), body.address, body.state
    if body.timezone:
        l.timezone = body.timezone
    l.geo_lat = str(body.geo_lat) if body.geo_lat is not None else None
    l.geo_lng = str(body.geo_lng) if body.geo_lng is not None else None
    if body.legal_entity_id:
        l.legal_entity_id = body.legal_entity_id


@router.post("/locations", status_code=201)
def add_location(body: LocationIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import LegalEntity, Location

    tenant = _admin(db, current_user)
    l = Location(tenant_id=tenant.tenant_id)
    _apply(l, body)
    if l.legal_entity_id is None:
        first = db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id).order_by(LegalEntity.name).first()
        l.legal_entity_id = first.id if first else None
    db.add(l)
    db.commit()
    log_action(db, "location", l.id, "location_added", current_user.email[:50], {"name": l.name})
    return _loc_row(l)


@router.patch("/locations/{location_id}")
def edit_location(location_id: uuid.UUID, body: LocationIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import Location

    tenant = _admin(db, current_user)
    l = db.query(Location).filter(Location.tenant_id == tenant.tenant_id, Location.id == location_id).first()
    if l is None:
        raise HTTPException(status_code=404, detail="Office not found")
    _apply(l, body)
    db.commit()
    log_action(db, "location", l.id, "location_updated", current_user.email[:50], {"name": l.name})
    return _loc_row(l)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy.exc import IntegrityError

    from app.models.core_hr import Location

    tenant = _admin(db, current_user)
    l = db.query(Location).filter(Location.tenant_id == tenant.tenant_id, Location.id == location_id).first()
    if l is None:
        return None
    name = l.name
    try:
        db.delete(l)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="People or jobs still use this office. Move them to another office first.")
    log_action(db, "location", location_id, "location_deleted", current_user.email[:50], {"name": name})
    return None
