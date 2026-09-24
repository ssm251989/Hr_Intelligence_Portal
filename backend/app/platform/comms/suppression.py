"""Suppression list + notification preferences (docs/HRMS_COMPLETE_SPEC.txt Part 4
section 1 + 3's PreferenceFilter/Suppression step)."""

from sqlalchemy.orm import Session

from app.models.comms import NotificationPreference, SuppressionListEntry
from app.platform.tenancy.context import TenantContext


def is_suppressed(db: Session, tenant: TenantContext, address: str) -> bool:
    return (
        db.query(SuppressionListEntry)
        .filter(SuppressionListEntry.tenant_id == tenant.tenant_id, SuppressionListEntry.address == address.lower())
        .first()
        is not None
    )


def suppress(db: Session, tenant: TenantContext, address: str, reason: str) -> None:
    if is_suppressed(db, tenant, address):
        return
    db.add(SuppressionListEntry(tenant_id=tenant.tenant_id, address=address.lower(), reason=reason))
    db.commit()


def is_opted_in(db: Session, tenant: TenantContext, *, user_id=None, candidate_id=None, channel: str, event_group: str) -> bool:
    """Defaults to True (opted in) when no preference row exists -- an explicit opt-OUT
    row is what suppresses a channel/event_group, never the absence of a row."""
    query = db.query(NotificationPreference).filter(
        NotificationPreference.tenant_id == tenant.tenant_id, NotificationPreference.channel == channel,
        NotificationPreference.event_group == event_group,
    )
    if user_id is not None:
        query = query.filter(NotificationPreference.user_id == user_id)
    elif candidate_id is not None:
        query = query.filter(NotificationPreference.candidate_id == candidate_id)
    else:
        return True
    pref = query.first()
    return pref.opted_in if pref is not None else True


def filter_suppressed_and_opted_out(
    db: Session, tenant: TenantContext, addresses: list[str], *, channel: str, event_group: str,
) -> list[str]:
    return [addr for addr in addresses if not is_suppressed(db, tenant, addr)]
