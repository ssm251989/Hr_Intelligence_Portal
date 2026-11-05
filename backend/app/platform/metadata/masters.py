"""Masters/picklists (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 3) -- replaces every
enum that's business-specific (as opposed to a structural one like `applications.status`,
which stays a real CHECK-constrained column; see `hrctl.seed_masters`'s own docstring for
why `candidates.source` -- a genuine business-specific enum -- is seeded as DATA here
without removing its existing CheckConstraint safety net).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.metadata import MasterType, MasterValue
from app.platform.tenancy.context import TenantContext

MASTER_TYPES = (
    ("designation", "Designation", False), ("grade", "Grade", False), ("band", "Band", False),
    ("employment_type", "Employment Type", False), ("worker_type", "Worker Type", False),
    ("job_family", "Job Family", False), ("skill", "Skill", False), ("skill_category", "Skill Category", False),
    ("education_level", "Education Level", False), ("institution", "Institution", False),
    ("source_of_hire", "Source of Hire", False), ("rejection_reason", "Rejection Reason", False),
    ("exit_reason", "Exit Reason", False), ("document_type", "Document Type", False),
    ("asset_category", "Asset Category", False), ("ticket_category", "Ticket Category", False),
    ("relationship", "Relationship", False), ("blood_group", "Blood Group", False),
    ("language", "Language", False), ("industry", "Industry", False), ("notice_period", "Notice Period", False),
    ("currency", "Currency", False), ("country", "Country", True), ("state", "State", True), ("city", "City", True),
)


def register_master_types(db: Session) -> None:
    """Idempotent -- the TYPE catalog itself is platform-wide (not TenantOwned, see
    app.models.metadata.MasterType's own docstring), same register_all() pattern as every
    other module's registry."""
    for code, name, hierarchical in MASTER_TYPES:
        if db.get(MasterType, code) is None:
            db.add(MasterType(code=code, name=name, hierarchical=hierarchical))
    db.commit()


def list_values(db: Session, tenant: TenantContext, type_code: str, *, include_inactive: bool = False, as_of: Optional[datetime] = None) -> list[MasterValue]:
    query = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == type_code)
    if not include_inactive:
        query = query.filter(MasterValue.is_active.is_(True))
        as_of = as_of or datetime.now(timezone.utc)
        query = query.filter((MasterValue.effective_from.is_(None)) | (MasterValue.effective_from <= as_of))
        query = query.filter((MasterValue.effective_to.is_(None)) | (MasterValue.effective_to >= as_of))
    return query.order_by(MasterValue.sort, MasterValue.code).all()


def create_value(
    db: Session, tenant: TenantContext, *, type_code: str, code: str, label_i18n: dict,
    parent_id: Optional[UUID] = None, attributes: Optional[dict] = None, sort: int = 0,
    effective_from: Optional[datetime] = None, effective_to: Optional[datetime] = None,
) -> MasterValue:
    value = MasterValue(
        tenant_id=tenant.tenant_id, type_code=type_code, code=code, label_i18n=label_i18n,
        parent_id=parent_id, attributes_json=attributes or {}, sort=sort,
        effective_from=effective_from, effective_to=effective_to,
    )
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def deactivate_value(db: Session, tenant: TenantContext, value_id: UUID) -> None:
    value = db.get(MasterValue, value_id)
    if value is not None and value.tenant_id == tenant.tenant_id:
        value.is_active = False
        db.commit()
