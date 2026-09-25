"""Employee documents + expiry alerts (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 4)."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import EmployeeDocument
from app.platform.tenancy.context import TenantContext


def add_document(
    db: Session, tenant: TenantContext, *, employee_id: UUID, doc_type: str, file_ref: Optional[str] = None,
    issued_date: Optional[date] = None, expiry_date: Optional[date] = None, visibility: str = "hr",
) -> EmployeeDocument:
    doc = EmployeeDocument(
        tenant_id=tenant.tenant_id, employee_id=employee_id, type=doc_type, file_ref=file_ref,
        issued_date=issued_date, expiry_date=expiry_date, visibility=visibility,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def documents_for(db: Session, tenant: TenantContext, employee_id: UUID) -> list[EmployeeDocument]:
    return db.query(EmployeeDocument).filter(EmployeeDocument.tenant_id == tenant.tenant_id, EmployeeDocument.employee_id == employee_id).all()


def check_expiring_documents(db: Session, tenant: TenantContext, *, within_days: int = 30) -> list[EmployeeDocument]:
    """Real, directly-callable (and directly testable) -- emits `document.expiring` for
    every document expiring within `within_days`. Nothing calls this on a schedule yet
    (same documented Celery-beat gap as everywhere else in this build); a real caller
    would be a daily beat job once one exists."""
    from app.core_hr.events import emit_document_expiring

    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=within_days)
    expiring = (
        db.query(EmployeeDocument)
        .filter(EmployeeDocument.tenant_id == tenant.tenant_id, EmployeeDocument.expiry_date.isnot(None))
        .filter(EmployeeDocument.expiry_date >= today, EmployeeDocument.expiry_date <= cutoff)
        .all()
    )
    for doc in expiring:
        emit_document_expiring(db, tenant, employee_id=doc.employee_id, document_id=doc.id, expiry_date=doc.expiry_date.isoformat())
    return expiring
