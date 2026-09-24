"""IAM management API (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 4) -- roles, role
assignments, field security, delegations, admin MFA reset, access review, impersonation.
Gated by `authz.require(...)` throughout (not `require_roles("admin")`) -- a deliberate
proof point that the new permission system enforces its OWN management surface, not just
new business endpoints; every existing admin user already resolves these permissions via
`roles.py`'s flat-role bridge (admin -> Super Admin -> every permission), so this is not a
regression for any current admin.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.iam import FieldSecurity, Role, RoleAssignment, UserDelegation
from app.models.user import User
from app.platform.iam import mfa
from app.platform.iam.authz import require
from app.platform.iam.delegation import InvalidDelegationWindowError, active_delegations_for, create_delegation, revoke_delegation
from app.platform.iam.permissions import all_permissions
from app.platform.iam.roles import sync_system_roles
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/iam", tags=["iam"])


# ---- permissions catalog (read-only, for a role editor's checkbox list) ----


class PermissionRead(BaseModel):
    code: str
    module: str
    resource: str
    action: str


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(current_user: User = Depends(require("iam.roles.view"))):
    return [PermissionRead(code=p.code, module=p.module, resource=p.resource, action=p.action) for p in all_permissions()]


# ---- roles ----


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    permissions: Optional[list[str]] = None


class RoleRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    is_system: bool
    permissions: list[str]


def _role_read(r: Role) -> RoleRead:
    return RoleRead(id=r.id, name=r.name, description=r.description, is_system=r.is_system, permissions=list(r.permissions or []))


@router.get("/roles", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), current_user: User = Depends(require("iam.roles.view"))):
    tenant = require_current_tenant()
    sync_system_roles(db, tenant)  # ensures the seeded templates exist/are current before listing
    rows = db.query(Role).filter(Role.tenant_id == tenant.tenant_id).order_by(Role.name).all()
    return [_role_read(r) for r in rows]


@router.post("/roles", response_model=RoleRead, status_code=201)
def create_role(payload: RoleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("iam.roles.configure"))):
    tenant = require_current_tenant()
    role = Role(tenant_id=tenant.tenant_id, name=payload.name, description=payload.description, permissions=payload.permissions, is_system=False)
    db.add(role)
    db.commit()
    db.refresh(role)
    log_action(db, "role", role.id, "role_created", current_user.email, {"name": role.name})
    return _role_read(role)


@router.patch("/roles/{role_id}", response_model=RoleRead)
def update_role(role_id: UUID, payload: RoleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("iam.roles.configure"))):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        role.permissions = payload.permissions
    db.commit()
    db.refresh(role)
    log_action(db, "role", role.id, "role_updated", current_user.email, {"permissions": role.permissions})
    return _role_read(role)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("iam.roles.configure"))):
    role = db.get(Role, role_id)
    if role is None:
        return
    if role.is_system:
        raise HTTPException(status_code=400, detail="System role templates cannot be deleted -- clone it into a custom role instead")
    db.delete(role)
    db.commit()
    log_action(db, "role", role_id, "role_deleted", current_user.email, {})


# ---- role assignments ----


class RoleAssignmentCreate(BaseModel):
    user_id: UUID
    role_id: UUID
    scope_type: str = "all"
    scope_ids: list[UUID] = []
    condition_jsonlogic: Optional[dict] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class RoleAssignmentRead(BaseModel):
    id: UUID
    user_id: UUID
    role_id: UUID
    scope_type: str
    scope_ids: list[UUID]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]


def _assignment_read(a: RoleAssignment) -> RoleAssignmentRead:
    return RoleAssignmentRead(id=a.id, user_id=a.user_id, role_id=a.role_id, scope_type=a.scope_type, scope_ids=list(a.scope_ids or []), valid_from=a.valid_from, valid_to=a.valid_to)


@router.get("/role-assignments", response_model=list[RoleAssignmentRead])
def list_role_assignments(user_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("iam.role_assignments.view"))):
    tenant = require_current_tenant()
    query = db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id)
    if user_id is not None:
        query = query.filter(RoleAssignment.user_id == user_id)
    return [_assignment_read(a) for a in query.all()]


@router.post("/role-assignments", response_model=RoleAssignmentRead, status_code=201)
def create_role_assignment(payload: RoleAssignmentCreate, db: Session = Depends(get_db), current_user: User = Depends(require("iam.role_assignments.configure"))):
    tenant = require_current_tenant()
    assignment = RoleAssignment(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    log_action(db, "role_assignment", assignment.id, "role_assigned", current_user.email, {"user_id": str(payload.user_id), "role_id": str(payload.role_id)})
    return _assignment_read(assignment)


@router.delete("/role-assignments/{assignment_id}", status_code=204)
def delete_role_assignment(assignment_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("iam.role_assignments.configure"))):
    assignment = db.get(RoleAssignment, assignment_id)
    if assignment is not None:
        db.delete(assignment)
        db.commit()
        log_action(db, "role_assignment", assignment_id, "role_unassigned", current_user.email, {})


# ---- field security ----


class FieldSecurityUpsert(BaseModel):
    entity: str
    field: str
    role_id: UUID
    access: str


class FieldSecurityRead(BaseModel):
    id: UUID
    entity: str
    field: str
    role_id: UUID
    access: str


@router.get("/field-security", response_model=list[FieldSecurityRead])
def list_field_security(entity: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("iam.field_security.view"))):
    tenant = require_current_tenant()
    query = db.query(FieldSecurity).filter(FieldSecurity.tenant_id == tenant.tenant_id)
    if entity is not None:
        query = query.filter(FieldSecurity.entity == entity)
    return [FieldSecurityRead(id=r.id, entity=r.entity, field=r.field, role_id=r.role_id, access=r.access) for r in query.all()]


@router.put("/field-security", response_model=FieldSecurityRead)
def upsert_field_security(payload: FieldSecurityUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("iam.field_security.configure"))):
    tenant = require_current_tenant()
    row = (
        db.query(FieldSecurity)
        .filter(FieldSecurity.tenant_id == tenant.tenant_id, FieldSecurity.entity == payload.entity, FieldSecurity.field == payload.field, FieldSecurity.role_id == payload.role_id)
        .first()
    )
    if row is None:
        row = FieldSecurity(tenant_id=tenant.tenant_id, entity=payload.entity, field=payload.field, role_id=payload.role_id, access=payload.access)
        db.add(row)
    else:
        row.access = payload.access
    db.commit()
    db.refresh(row)
    return FieldSecurityRead(id=row.id, entity=row.entity, field=row.field, role_id=row.role_id, access=row.access)


@router.delete("/field-security/{rule_id}", status_code=204)
def delete_field_security(rule_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("iam.field_security.configure"))):
    row = db.get(FieldSecurity, rule_id)
    if row is not None:
        db.delete(row)
        db.commit()


# ---- delegations ----


class DelegationCreate(BaseModel):
    to_user_id: UUID
    starts_at: datetime
    ends_at: datetime
    permissions: Optional[list[str]] = None


class DelegationRead(BaseModel):
    id: UUID
    from_user_id: UUID
    to_user_id: UUID
    permissions: Optional[list[str]]
    starts_at: datetime
    ends_at: datetime


def _delegation_read(d: UserDelegation) -> DelegationRead:
    return DelegationRead(id=d.id, from_user_id=d.from_user_id, to_user_id=d.to_user_id, permissions=d.permissions, starts_at=d.starts_at, ends_at=d.ends_at)


@router.get("/delegations", response_model=list[DelegationRead])
def list_my_delegations(current_user: User = Depends(require("iam.delegations.view")), db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    out_going = active_delegations_for(db, tenant, current_user.id, as_delegate=False)
    incoming = active_delegations_for(db, tenant, current_user.id, as_delegate=True)
    return [_delegation_read(d) for d in {*out_going, *incoming}]


@router.post("/delegations", response_model=DelegationRead, status_code=201)
def create_my_delegation(payload: DelegationCreate, current_user: User = Depends(require("iam.delegations.create")), db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    try:
        delegation = create_delegation(
            db, tenant, from_user_id=current_user.id, to_user_id=payload.to_user_id,
            starts_at=payload.starts_at, ends_at=payload.ends_at, permissions=payload.permissions,
        )
    except InvalidDelegationWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _delegation_read(delegation)


@router.delete("/delegations/{delegation_id}", status_code=204)
def delete_my_delegation(delegation_id: UUID, current_user: User = Depends(require("iam.delegations.view")), db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    delegation = db.get(UserDelegation, delegation_id)
    if delegation is not None and delegation.from_user_id == current_user.id:
        revoke_delegation(db, tenant, delegation_id)


# ---- admin MFA reset ----


@router.post("/users/{user_id}/mfa/reset", status_code=204)
def admin_reset_mfa(user_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("iam.roles.configure"))):
    tenant = require_current_tenant()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    mfa.disable_totp(db, tenant, target)
    target.mfa_email_otp_enabled = False
    db.commit()
    log_action(db, "user", user_id, "mfa_admin_reset", current_user.email, {})


# ---- access review report ----


class AccessReviewRow(BaseModel):
    user_id: UUID
    email: str
    full_name: Optional[str]
    role_names: list[str]


@router.get("/access-review", response_model=list[AccessReviewRow])
def access_review(permission: str, db: Session = Depends(get_db), current_user: User = Depends(require("iam.access_review.view"))):
    """"Who can see salary / Aadhaar" (section 4's own example) -- every user who
    currently resolves `permission` through an active role_assignment, with which role(s)
    grant it. Delegation is deliberately excluded -- a report of WHO HOLDS a permission
    should show its real owners, not everyone a temporary delegate could reach."""
    tenant = require_current_tenant()
    now = datetime.now(timezone.utc)
    assignments = (
        db.query(RoleAssignment)
        .filter(RoleAssignment.tenant_id == tenant.tenant_id)
        .filter((RoleAssignment.valid_from.is_(None)) | (RoleAssignment.valid_from <= now))
        .filter((RoleAssignment.valid_to.is_(None)) | (RoleAssignment.valid_to >= now))
        .all()
    )
    by_user: dict[UUID, list[str]] = {}
    for assignment in assignments:
        role = db.get(Role, assignment.role_id)
        if role is not None and permission in (role.permissions or []):
            by_user.setdefault(assignment.user_id, []).append(role.name)

    rows = []
    for user_id, role_names in by_user.items():
        user = db.get(User, user_id)
        if user is not None:
            rows.append(AccessReviewRow(user_id=user_id, email=user.email, full_name=user.full_name, role_names=sorted(set(role_names))))
    return sorted(rows, key=lambda r: r.email)


# ---- impersonation ("view as user") ----


class ImpersonationResponse(BaseModel):
    access_token: str


@router.post("/impersonate/{user_id}", response_model=ImpersonationResponse)
def impersonate(user_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("iam.impersonation.create"))):
    from app.core.security import create_access_token

    tenant = require_current_tenant()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    log_action(db, "user", user_id, "impersonation_started", current_user.email, {"impersonated_by": current_user.email})
    token = create_access_token(subject=str(target.id), extra_claims={"tid": str(tenant.tenant_id), "impersonated_by": str(current_user.id)})
    return ImpersonationResponse(access_token=token)
