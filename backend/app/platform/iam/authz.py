"""authz.require(permission)/authz.scope_filter(...) (docs/HRMS_COMPLETE_SPEC.txt Part 5A
section 2). Resolves a user's EFFECTIVE permission set from their own `role_assignments`
(each row's `valid_from`/`valid_to` window applied) plus anything delegated to them via an
active `user_delegations` row -- never the flat `users.role` column, which
`require_roles()` (app/auth/dependencies.py) still owns exclusively; see this package's
own `roles.py` for how the two are bridged for existing users.

**scope_filter's org-hierarchy scope types are honestly unsupported, not silently
no-op'd**: `legal_entity`/`business_unit`/`location`/`department`/`cost_center`/
`reportees_direct`/`reportees_all` all need Part 7's Core HR org model (employees,
managers, departments) to mean anything -- that data doesn't exist yet. A role_assignment
actually using one of those scope_types makes `scope_filter()` raise
`ScopeNotSupportedError` rather than quietly returning an unfiltered (or wrongly filtered)
query -- the safe failure mode for an authorization filter is "refuse", never "leak"."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Query, Session

from app.models.iam import Role, RoleAssignment, UserDelegation
from app.models.user import User
from app.platform.tenancy.context import TenantContext


class ScopeNotSupportedError(Exception):
    pass


def active_role_assignments(db: Session, tenant: TenantContext, user_id) -> list[RoleAssignment]:
    now = datetime.now(timezone.utc)
    rows = db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user_id).all()
    return [
        r for r in rows
        if (r.valid_from is None or r.valid_from <= now) and (r.valid_to is None or r.valid_to >= now)
    ]


def _delegated_user_ids(db: Session, tenant: TenantContext, to_user_id) -> list[tuple]:
    """Returns [(from_user_id, permissions_or_None), ...] for every currently-active
    delegation INTO to_user_id -- permissions_or_None mirrors user_delegations.permissions'
    own "NULL means all of from_user's permissions" convention."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserDelegation)
        .filter(
            UserDelegation.tenant_id == tenant.tenant_id, UserDelegation.to_user_id == to_user_id,
            UserDelegation.starts_at <= now, UserDelegation.ends_at >= now,
        )
        .all()
    )
    return [(d.from_user_id, d.permissions) for d in rows]


def effective_permissions(db: Session, tenant: TenantContext, user: User) -> set[str]:
    codes: set[str] = set()
    for assignment in active_role_assignments(db, tenant, user.id):
        role = db.get(Role, assignment.role_id)
        if role is not None:
            codes.update(role.permissions or [])

    for from_user_id, only_these in _delegated_user_ids(db, tenant, user.id):
        from_user = db.get(User, from_user_id)
        if from_user is None:
            continue
        delegated = effective_permissions(db, tenant, from_user)
        codes.update(delegated if only_these is None else (delegated & set(only_these)))

    return codes


def has_permission(db: Session, tenant: TenantContext, user: User, permission_code: str) -> bool:
    return permission_code in effective_permissions(db, tenant, user)


def effective_scope_types(db: Session, tenant: TenantContext, user: User, permission_code: str) -> set[str]:
    """The union of scope_type across every active role_assignment whose role actually
    grants permission_code -- what scope_filter() below applies. Delegation is
    deliberately excluded here: a delegate acts within THEIR OWN scope, never a wider one
    borrowed from the delegator, so delegated access never widens a scope_filter."""
    scopes: set[str] = set()
    for assignment in active_role_assignments(db, tenant, user.id):
        role = db.get(Role, assignment.role_id)
        if role is not None and permission_code in (role.permissions or []):
            scopes.add(assignment.scope_type)
    return scopes


_ORG_HIERARCHY_SCOPES = {"legal_entity", "business_unit", "location", "department", "cost_center", "reportees_direct", "reportees_all"}


def scope_filter(
    query: Query, *, model, permission_code: str, user: User, db: Session, tenant: TenantContext,
    owner_column=None,
) -> Query:
    """`owner_column` is the caller's own `model.some_user_fk` for what "self" scope means
    on THIS model -- there's no universal "owner" column across every entity, so the
    caller (the one router that actually knows this model's shape) supplies it; omit it
    if this model has no "self" concept (raises ScopeNotSupportedError if a role actually
    needs it)."""
    scopes = effective_scope_types(db, tenant, user, permission_code)
    if not scopes or "all" in scopes:
        return query

    unsupported = scopes & _ORG_HIERARCHY_SCOPES
    if unsupported:
        raise ScopeNotSupportedError(
            f"scope_type(s) {sorted(unsupported)} on permission {permission_code!r} need Part 7's "
            "Core HR org model (employees/managers/departments), not built yet."
        )

    if "self" in scopes:
        if owner_column is None:
            raise ScopeNotSupportedError(f"permission {permission_code!r} has scope_type='self' but no owner_column was supplied for {model.__name__}")
        return query.filter(owner_column == user.id)

    if "custom" in scopes:
        # condition_jsonlogic-based scopes need the specific row's data to evaluate
        # against -- meaningful per-row, not as a single SQL WHERE, so a "custom"-scoped
        # caller filters in Python per-row via `permits_row()` below instead of here.
        raise ScopeNotSupportedError(f"permission {permission_code!r} has scope_type='custom' -- use permits_row() per-row, not scope_filter()")

    return query


def permits_row(db: Session, tenant: TenantContext, user: User, permission_code: str, row_context: dict) -> bool:
    """Per-row check for scope_type='custom' role_assignments (condition_jsonlogic
    evaluated against row_context) -- also correctly permits when the user instead holds
    the SAME permission at 'all' or 'self'-already-filtered scope (those don't need a
    per-row check at all, so this returns True immediately for them)."""
    from json_logic import jsonLogic

    scopes = effective_scope_types(db, tenant, user, permission_code)
    if "all" in scopes:
        return True
    if "custom" not in scopes:
        return bool(scopes)  # 'self'/org-hierarchy scopes are pre-filtered by scope_filter(); nothing left to deny here

    for assignment in active_role_assignments(db, tenant, user.id):
        if assignment.scope_type != "custom" or assignment.condition_jsonlogic is None:
            continue
        role = db.get(Role, assignment.role_id)
        if role is not None and permission_code in (role.permissions or []) and jsonLogic(assignment.condition_jsonlogic, row_context):
            return True
    return False


def require(permission_code: str):
    """FastAPI dependency factory -- `Depends(authz.require("recruitment.job.edit"))`."""
    from fastapi import Depends, HTTPException

    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.platform.tenancy.context import require_current_tenant

    def _dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        tenant = require_current_tenant()
        if not has_permission(db, tenant, current_user, permission_code):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_code}")
        return current_user

    return _dependency
