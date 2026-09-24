"""user_delegations CRUD helpers (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 2's own
"cover while someone is away"). `authz.effective_permissions()`/`has_permission()` already
apply an active delegation automatically -- this module is only the create/list/revoke
surface the API router calls."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.iam import UserDelegation
from app.platform.tenancy.context import TenantContext


class InvalidDelegationWindowError(Exception):
    pass


def create_delegation(
    db: Session, tenant: TenantContext, *, from_user_id: UUID, to_user_id: UUID,
    starts_at: datetime, ends_at: datetime, permissions: list[str] | None = None,
) -> UserDelegation:
    if ends_at <= starts_at:
        raise InvalidDelegationWindowError("ends_at must be after starts_at")
    if from_user_id == to_user_id:
        raise InvalidDelegationWindowError("cannot delegate to yourself")
    delegation = UserDelegation(
        tenant_id=tenant.tenant_id, from_user_id=from_user_id, to_user_id=to_user_id,
        permissions=permissions, starts_at=starts_at, ends_at=ends_at,
    )
    db.add(delegation)
    db.commit()
    db.refresh(delegation)
    return delegation


def active_delegations_for(db: Session, tenant: TenantContext, user_id: UUID, *, as_delegate: bool = True) -> list[UserDelegation]:
    """as_delegate=True: delegations INTO user_id (they're covering someone). False:
    delegations user_id has handed OUT (they're the one away)."""
    now = datetime.now(timezone.utc)
    column = UserDelegation.to_user_id if as_delegate else UserDelegation.from_user_id
    return (
        db.query(UserDelegation)
        .filter(UserDelegation.tenant_id == tenant.tenant_id, column == user_id, UserDelegation.starts_at <= now, UserDelegation.ends_at >= now)
        .all()
    )


def revoke_delegation(db: Session, tenant: TenantContext, delegation_id: UUID) -> None:
    delegation = db.get(UserDelegation, delegation_id)
    if delegation is not None and delegation.tenant_id == tenant.tenant_id:
        db.delete(delegation)
        db.commit()
