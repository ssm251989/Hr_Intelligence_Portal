"""Org-hierarchy data scopes (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 2 scope types),
resolved against Part 7's Core HR model now that it exists. `authz.scope_filter()` still
refuses these scope types for arbitrary models (it can't know how a model relates to an
employee); anything that CAN express itself as "rows about employee X" -- Part 12's
datasets, the copilot's personal-data tools -- uses `employee_ids_in_scope()` here.

Return value: `None` = unrestricted ("all"), otherwise the exact set of employee ids the
user may see for that permission (possibly empty -> sees nothing).
"""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import Employee, EmploymentRecord
from app.models.iam import Role
from app.models.user import User
from app.platform.iam.authz import active_role_assignments
from app.platform.tenancy.context import TenantContext

_FIELD_FOR_SCOPE = {
    "legal_entity": EmploymentRecord.legal_entity_id,
    "business_unit": EmploymentRecord.business_unit_id,
    "location": EmploymentRecord.location_id,
    "department": EmploymentRecord.department_id,
    "cost_center": EmploymentRecord.cost_center_id,
}
_MAX_DEPTH = 25


def _current_records(db: Session, tenant: TenantContext, as_of: date):
    return (
        db.query(EmploymentRecord)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_from <= as_of)
        .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= as_of))
    )


def my_employee_id(db: Session, tenant: TenantContext, user: User) -> Optional[UUID]:
    row = db.query(Employee.id).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()
    return row[0] if row else None


def direct_reportees(db: Session, tenant: TenantContext, manager_employee_id: UUID, *, as_of: Optional[date] = None) -> set[UUID]:
    as_of = as_of or datetime.now(timezone.utc).date()
    return {r.employee_id for r in _current_records(db, tenant, as_of).filter(EmploymentRecord.manager_employee_id == manager_employee_id).all()}


def all_reportees(db: Session, tenant: TenantContext, manager_employee_id: UUID, *, as_of: Optional[date] = None) -> set[UUID]:
    """Transitive; cycle-safe (a bad manager loop can't recurse forever)."""
    seen: set[UUID] = set()
    frontier = {manager_employee_id}
    for _ in range(_MAX_DEPTH):
        nxt: set[UUID] = set()
        for manager_id in frontier:
            nxt |= direct_reportees(db, tenant, manager_id, as_of=as_of)
        nxt -= seen | {manager_employee_id}
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    return seen


def employee_ids_in_scope(db: Session, tenant: TenantContext, user: User, permission_code: str, *, as_of: Optional[date] = None) -> Optional[set[UUID]]:
    as_of = as_of or datetime.now(timezone.utc).date()
    me = my_employee_id(db, tenant, user)
    allowed: set[UUID] = set()
    granted = False
    for assignment in active_role_assignments(db, tenant, user.id):
        role = db.get(Role, assignment.role_id)
        if role is None or permission_code not in (role.permissions or []):
            continue
        granted = True
        scope = assignment.scope_type
        if scope == "all":
            return None
        if scope == "self":
            if me:
                allowed.add(me)
        elif scope == "reportees_direct":
            if me:
                allowed |= direct_reportees(db, tenant, me, as_of=as_of)
        elif scope == "reportees_all":
            if me:
                allowed |= all_reportees(db, tenant, me, as_of=as_of)
        elif scope in _FIELD_FOR_SCOPE:
            ids = list(assignment.scope_ids or [])
            if ids:
                allowed |= {r.employee_id for r in _current_records(db, tenant, as_of).filter(_FIELD_FOR_SCOPE[scope].in_(ids)).all()}
        # "custom" is per-row (authz.permits_row); contributes nothing to a set filter
    return allowed if granted else set()
