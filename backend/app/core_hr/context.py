"""The flat, JSONLogic-friendly view of one employee that rule engines evaluate against
(review-cycle eligibility in Part 10, dataset scoping and agents in Part 12, separation
policies in Part 11) -- one definition so every rule sees the same field names."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core_hr import lifecycle
from app.models.core_hr import Employee, EmploymentRecord
from app.platform.tenancy.context import TenantContext


def hire_date(db: Session, tenant: TenantContext, employee: Employee) -> Optional[date]:
    first = (
        db.query(EmploymentRecord)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id == employee.id)
        .order_by(EmploymentRecord.effective_from.asc())
        .first()
    )
    return first.effective_from if first else None


def employee_context(db: Session, tenant: TenantContext, employee: Employee, *, as_of: Optional[date] = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc).date()
    current = lifecycle.get_current_employment(db, tenant, employee.id, as_of=as_of)
    doj = hire_date(db, tenant, employee)

    def _s(value):
        return str(value) if value is not None else None

    return {
        "employee_id": str(employee.id), "employee_code": employee.employee_code, "status": employee.status,
        "worker_type": employee.worker_type, "gender": employee.gender,
        "legal_entity_id": _s(current.legal_entity_id) if current else None,
        "business_unit_id": _s(current.business_unit_id) if current else None,
        "department_id": _s(current.department_id) if current else None,
        "location_id": _s(current.location_id) if current else None,
        "position_id": _s(current.position_id) if current else None,
        "designation": current.designation if current else None, "grade": current.grade if current else None,
        "employment_type": current.employment_type if current else None,
        "manager_employee_id": _s(current.manager_employee_id) if current else None,
        "probation_end": current.probation_end.isoformat() if current and current.probation_end else None,
        "confirmed": bool(current and current.confirmation_date and current.confirmation_date <= as_of),
        "hire_date": doj.isoformat() if doj else None,
        "tenure_days": (as_of - doj).days if doj else 0,
        **{f"cf_{k}": v for k, v in (employee.custom_fields or {}).items()},
    }


def manager_of(db: Session, tenant: TenantContext, employee_id, *, as_of: Optional[date] = None):
    current = lifecycle.get_current_employment(db, tenant, employee_id, as_of=as_of)
    return current.manager_employee_id if current else None
