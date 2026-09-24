"""field_security (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 2) -- an ALLOWLIST-EXCEPTION
mechanism: a field with no matching row for any of a user's roles is unrestricted
(access="write") by default; an explicit row only ever RESTRICTS a specific role's access
to a specific field. When a user holds multiple roles with differing rules for the same
field, the MOST PERMISSIVE of their own roles' rules wins (a second role should only ever
add ability, never take it away -- consistent with how `authz.effective_permissions()`
already unions across role_assignments rather than intersecting them).
"""

from sqlalchemy.orm import Session

from app.models.iam import FieldSecurity
from app.models.user import User
from app.platform.iam.authz import active_role_assignments
from app.platform.tenancy.context import TenantContext

_ACCESS_RANK = {"hidden": 0, "masked": 1, "read": 2, "write": 3}
_MASK_VALUE = "••••"


def _role_ids_for(db: Session, tenant: TenantContext, user: User) -> list:
    return [a.role_id for a in active_role_assignments(db, tenant, user.id)]


def _field_access_map(db: Session, tenant: TenantContext, user: User, entity: str) -> dict[str, str]:
    role_ids = _role_ids_for(db, tenant, user)
    if not role_ids:
        return {}
    rows = (
        db.query(FieldSecurity)
        .filter(FieldSecurity.tenant_id == tenant.tenant_id, FieldSecurity.entity == entity, FieldSecurity.role_id.in_(role_ids))
        .all()
    )
    best: dict[str, str] = {}
    for row in rows:
        current = best.get(row.field)
        if current is None or _ACCESS_RANK[row.access] > _ACCESS_RANK[current]:
            best[row.field] = row.access
    return best


def apply_field_security(db: Session, tenant: TenantContext, user: User, entity: str, obj: dict) -> dict:
    """Read-side: hidden fields are removed entirely (never even a masked placeholder --
    their EXISTENCE isn't implied), masked fields become `_MASK_VALUE`, read/write/
    unlisted fields pass through unchanged."""
    access_map = _field_access_map(db, tenant, user, entity)
    if not access_map:
        return dict(obj)
    result = {}
    for key, value in obj.items():
        access = access_map.get(key, "write")
        if access == "hidden":
            continue
        result[key] = _MASK_VALUE if access == "masked" else value
    return result


def filter_write_fields(db: Session, tenant: TenantContext, user: User, entity: str, payload: dict) -> dict:
    """Write-side companion: strips any field the user's roles cap below 'write' (hidden/
    masked/read-only) out of an update payload, so a client can't smuggle a change to a
    field it was never shown/allowed to edit through a raw API call."""
    access_map = _field_access_map(db, tenant, user, entity)
    if not access_map:
        return dict(payload)
    return {key: value for key, value in payload.items() if access_map.get(key, "write") == "write"}
