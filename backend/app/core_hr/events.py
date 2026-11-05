"""Domain events (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 7) -- emitted through Part
4's own `dispatch_event()`, the same mechanism every other part's events already use.
Emitting an event that has no matching `notification_rules` row is a silent no-op (Part
4's own `NotificationRuleMatcher` behavior) -- these calls are safe to make unconditionally
even before any tenant has configured a rule for them."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.tenancy.context import TenantContext


def _dispatch(db: Session, tenant: TenantContext, event_type: str, context: dict) -> None:
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, event_type, context)


def emit_employee_created(db: Session, tenant: TenantContext, *, employee_id: UUID) -> None:
    _dispatch(db, tenant, "employee.created", {"employee_id": str(employee_id)})


def emit_employee_updated(db: Session, tenant: TenantContext, *, employee_id: UUID, changed_fields: list[str]) -> None:
    _dispatch(db, tenant, "employee.updated", {"employee_id": str(employee_id), "changed_fields": changed_fields})


def emit_employment_changed(db: Session, tenant: TenantContext, *, employee_id: UUID, event_type: str) -> None:
    _dispatch(db, tenant, "employment.changed", {"employee_id": str(employee_id), "event_type": event_type})


def emit_employee_status_changed(db: Session, tenant: TenantContext, *, employee_id: UUID, old_status: str, new_status: str) -> None:
    _dispatch(db, tenant, "employee.status_changed", {"employee_id": str(employee_id), "old_status": old_status, "new_status": new_status})


def emit_document_expiring(db: Session, tenant: TenantContext, *, employee_id: UUID, document_id: UUID, expiry_date: str) -> None:
    _dispatch(db, tenant, "document.expiring", {"employee_id": str(employee_id), "document_id": str(document_id), "expiry_date": expiry_date})
