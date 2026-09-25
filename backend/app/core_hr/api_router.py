"""Core HR API (docs/HRMS_COMPLETE_SPEC.txt Part 7) -- org model, employee master,
lifecycle events, documents, letters, import wizard. Gated by `authz.require(...)` (Part
5's `core_hr.*` permissions), same pattern as every platform API router since Part 5.
Scoped down the same way every other part's admin surface has been: plain CRUD + a
lazy-tree org chart, not the spec's own drag-drop org builder / PNG-PDF export / Leaflet
map (see docs/build_log.md's own Part 7 note).
"""

from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.core_hr import documents as documents_service
from app.core_hr import employees as employees_service
from app.core_hr import import_wizard
from app.core_hr import letters as letters_service
from app.core_hr import lifecycle
from app.core_hr import org as org_service
from app.models.core_hr import (
    BusinessUnit,
    CostCenter,
    Department,
    Employee,
    EmploymentRecord,
    LegalEntity,
    Location,
    Position,
)
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/core-hr", tags=["core-hr"])
public_router = APIRouter(prefix="/api/v1/public/core-hr", tags=["core-hr-public"])


# ---- legal entities ----


class LegalEntityCreate(BaseModel):
    name: str
    registration_ids_json: dict = {}
    address: Optional[str] = None
    currency: str = "INR"
    fiscal_year_start: str = "04-01"


class LegalEntityRead(BaseModel):
    id: UUID
    name: str
    address: Optional[str]
    currency: str
    fiscal_year_start: str


@router.get("/legal-entities", response_model=list[LegalEntityRead])
def list_legal_entities(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(LegalEntity).filter(LegalEntity.tenant_id == tenant.tenant_id).order_by(LegalEntity.name).all()
    return [LegalEntityRead(id=r.id, name=r.name, address=r.address, currency=r.currency, fiscal_year_start=r.fiscal_year_start) for r in rows]


@router.post("/legal-entities", response_model=LegalEntityRead, status_code=201)
def create_legal_entity(payload: LegalEntityCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = LegalEntity(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return LegalEntityRead(id=row.id, name=row.name, address=row.address, currency=row.currency, fiscal_year_start=row.fiscal_year_start)


# ---- business units / departments / locations / cost centers ----


class BusinessUnitCreate(BaseModel):
    name: str
    legal_entity_id: Optional[UUID] = None
    parent_id: Optional[UUID] = None


class BusinessUnitRead(BaseModel):
    id: UUID
    name: str
    legal_entity_id: Optional[UUID]
    parent_id: Optional[UUID]


@router.get("/business-units", response_model=list[BusinessUnitRead])
def list_business_units(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(BusinessUnit).filter(BusinessUnit.tenant_id == tenant.tenant_id).order_by(BusinessUnit.name).all()
    return [BusinessUnitRead(id=r.id, name=r.name, legal_entity_id=r.legal_entity_id, parent_id=r.parent_id) for r in rows]


@router.post("/business-units", response_model=BusinessUnitRead, status_code=201)
def create_business_unit(payload: BusinessUnitCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = BusinessUnit(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return BusinessUnitRead(id=row.id, name=row.name, legal_entity_id=row.legal_entity_id, parent_id=row.parent_id)


class DepartmentCreate(BaseModel):
    name: str
    business_unit_id: Optional[UUID] = None
    parent_id: Optional[UUID] = None


class DepartmentRead(BaseModel):
    id: UUID
    name: str
    business_unit_id: Optional[UUID]
    parent_id: Optional[UUID]


@router.get("/departments", response_model=list[DepartmentRead])
def list_departments(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(Department).filter(Department.tenant_id == tenant.tenant_id).order_by(Department.name).all()
    return [DepartmentRead(id=r.id, name=r.name, business_unit_id=r.business_unit_id, parent_id=r.parent_id) for r in rows]


@router.post("/departments", response_model=DepartmentRead, status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = Department(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return DepartmentRead(id=row.id, name=row.name, business_unit_id=row.business_unit_id, parent_id=row.parent_id)


@router.get("/departments/tree")
def department_tree(root_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    return org_service.department_tree(db, tenant, root_id)


class LocationCreate(BaseModel):
    name: str
    legal_entity_id: Optional[UUID] = None
    address: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    state: Optional[str] = None


class LocationRead(BaseModel):
    id: UUID
    name: str
    address: Optional[str]
    timezone: str
    state: Optional[str]


@router.get("/locations", response_model=list[LocationRead])
def list_locations(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name).all()
    return [LocationRead(id=r.id, name=r.name, address=r.address, timezone=r.timezone, state=r.state) for r in rows]


@router.post("/locations", response_model=LocationRead, status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = Location(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return LocationRead(id=row.id, name=row.name, address=row.address, timezone=row.timezone, state=row.state)


class CostCenterCreate(BaseModel):
    code: str
    name: str


class CostCenterRead(BaseModel):
    id: UUID
    code: str
    name: str


@router.get("/cost-centers", response_model=list[CostCenterRead])
def list_cost_centers(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(CostCenter).filter(CostCenter.tenant_id == tenant.tenant_id).order_by(CostCenter.code).all()
    return [CostCenterRead(id=r.id, code=r.code, name=r.name) for r in rows]


@router.post("/cost-centers", response_model=CostCenterRead, status_code=201)
def create_cost_center(payload: CostCenterCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = CostCenter(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return CostCenterRead(id=row.id, code=row.code, name=row.name)


# ---- positions + org chart ----


class PositionCreate(BaseModel):
    code: str
    title: str
    department_id: Optional[UUID] = None
    location_id: Optional[UUID] = None
    grade: Optional[str] = None
    reports_to_position_id: Optional[UUID] = None
    headcount_budget: int = 1
    is_critical: bool = False


class PositionRead(BaseModel):
    id: UUID
    code: str
    title: str
    department_id: Optional[UUID]
    location_id: Optional[UUID]
    grade: Optional[str]
    reports_to_position_id: Optional[UUID]
    status: str
    is_critical: bool


def _position_read(p: Position) -> PositionRead:
    return PositionRead(id=p.id, code=p.code, title=p.title, department_id=p.department_id, location_id=p.location_id, grade=p.grade, reports_to_position_id=p.reports_to_position_id, status=p.status, is_critical=p.is_critical)


@router.get("/positions", response_model=list[PositionRead])
def list_positions(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    rows = db.query(Position).filter(Position.tenant_id == tenant.tenant_id).order_by(Position.title).all()
    return [_position_read(p) for p in rows]


@router.get("/positions/search", response_model=list[PositionRead])
def search_positions(q: str, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    return [_position_read(p) for p in org_service.search_positions(db, tenant, q)]


@router.post("/positions", response_model=PositionRead, status_code=201)
def create_position(payload: PositionCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.create"))):
    tenant = require_current_tenant()
    row = Position(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _position_read(row)


class ReportsToUpdate(BaseModel):
    reports_to_position_id: Optional[UUID] = None


@router.patch("/positions/{position_id}/reports-to", response_model=PositionRead)
def update_reports_to(position_id: UUID, payload: ReportsToUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.edit"))):
    tenant = require_current_tenant()
    try:
        row = org_service.set_reports_to(db, tenant, position_id, payload.reports_to_position_id)
    except org_service.OrgChartCycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _position_read(row)


@router.get("/org-chart")
def org_chart(root_position_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    tenant = require_current_tenant()
    return org_service.org_chart_by_position(db, tenant, root_position_id)


# ---- employees ----


class EmployeeCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    status: str = "pre_hire"
    worker_type: str = "employee"
    personal_email: Optional[str] = None
    personal_phone: Optional[str] = None


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.create"))):
    tenant = require_current_tenant()
    employee = employees_service.create_employee(db, tenant, **payload.model_dump())
    from app.core_hr.events import emit_employee_created

    emit_employee_created(db, tenant, employee_id=employee.id)
    log_action(db, "employee", employee.id, "employee_created", current_user.email, {"employee_code": employee.employee_code})
    return employees_service.employee_to_dict(employee)


@router.get("/employees")
def list_employees(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    tenant = require_current_tenant()
    query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(Employee.status == status)
    return [employees_service.employee_to_dict(e) for e in query.order_by(Employee.employee_code).all()]


@router.get("/employees/{employee_id}")
def get_employee(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employees_service.employee_to_dict(employee)


class EncryptedFieldSet(BaseModel):
    field: str
    value: str


@router.put("/employees/{employee_id}/encrypted-field")
def set_encrypted_field(employee_id: UUID, payload: EncryptedFieldSet, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    tenant = require_current_tenant()
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        employees_service.set_encrypted_field(db, tenant, employee, payload.field, payload.value, created_by=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(db, "employee", employee_id, "sensitive_field_set", current_user.email, {"field": payload.field})
    return {"ok": True}


@router.get("/employees/{employee_id}/encrypted-field/{field}")
def reveal_encrypted_field(employee_id: UUID, field: str, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view_sensitive"))):
    """Every reveal is audited (section 2's own "PAN/bank masked, reveal button, every
    reveal audited" -- Part 6's own equivalent decision for field_security's masked
    fields, applied here to Core HR's own genuinely-encrypted fields)."""
    tenant = require_current_tenant()
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    value = employees_service.get_encrypted_field(db, tenant, employee, field)
    log_action(db, "employee", employee_id, "sensitive_field_revealed", current_user.email, {"field": field})
    return {"field": field, "value": value}


# ---- lifecycle events ----


class LifecycleEventRequest(BaseModel):
    event_type: str
    effective_from: date
    changes: dict[str, Any] = {}
    reason: Optional[str] = None


@router.post("/employees/{employee_id}/lifecycle-events")
def request_lifecycle_event(employee_id: UUID, payload: LifecycleEventRequest, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employment.create"))):
    tenant = require_current_tenant()
    try:
        result = lifecycle.request_event(
            db, tenant, employee_id=employee_id, event_type=payload.event_type, effective_from=payload.effective_from,
            changes=payload.changes, reason=payload.reason, created_by=current_user.email, requested_by_user_id=current_user.id,
        )
    except lifecycle.InvalidLifecycleEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(db, "employee", employee_id, "lifecycle_event_requested", current_user.email, {"event_type": payload.event_type, "applied": result["applied"]})
    if result["applied"]:
        return {"applied": True, "employment_record_id": str(result["record"].id)}
    return {"applied": False, "workflow_instance_id": str(result["workflow_instance_id"])}


@router.get("/employees/{employee_id}/employment-history")
def get_employment_history(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employment.view"))):
    tenant = require_current_tenant()
    rows = lifecycle.employment_history(db, tenant, employee_id)
    return [_employment_record_read(r) for r in rows]


@router.get("/employees/{employee_id}/employment-current")
def get_current_employment(employee_id: UUID, as_of: Optional[date] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employment.view"))):
    tenant = require_current_tenant()
    record = lifecycle.get_current_employment(db, tenant, employee_id, as_of=as_of)
    return _employment_record_read(record) if record else None


def _employment_record_read(r: EmploymentRecord) -> dict:
    return {
        "id": str(r.id), "employee_id": str(r.employee_id), "effective_from": r.effective_from.isoformat(),
        "effective_to": r.effective_to.isoformat() if r.effective_to else None, "event_type": r.event_type,
        "event_reason": r.event_reason, "department_id": str(r.department_id) if r.department_id else None,
        "position_id": str(r.position_id) if r.position_id else None, "designation": r.designation, "grade": r.grade,
        "manager_employee_id": str(r.manager_employee_id) if r.manager_employee_id else None, "work_mode": r.work_mode,
    }


# ---- documents ----


class DocumentCreate(BaseModel):
    doc_type: str
    file_ref: Optional[str] = None
    issued_date: Optional[date] = None
    expiry_date: Optional[date] = None
    visibility: str = "hr"


@router.post("/employees/{employee_id}/documents", status_code=201)
def add_document(employee_id: UUID, payload: DocumentCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    tenant = require_current_tenant()
    doc = documents_service.add_document(db, tenant, employee_id=employee_id, **payload.model_dump())
    return {"id": str(doc.id), "type": doc.type, "expiry_date": doc.expiry_date.isoformat() if doc.expiry_date else None}


@router.get("/employees/{employee_id}/documents")
def list_documents(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    tenant = require_current_tenant()
    docs = documents_service.documents_for(db, tenant, employee_id)
    return [{"id": str(d.id), "type": d.type, "issued_date": d.issued_date.isoformat() if d.issued_date else None, "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None, "visibility": d.visibility} for d in docs]


# ---- letters ----


class LetterTemplateCreate(BaseModel):
    key: str
    name: str
    html_tpl: str
    variables_schema: dict = {}


@router.post("/letter-templates", status_code=201)
def create_letter_template(payload: LetterTemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.create"))):
    tenant = require_current_tenant()
    template = letters_service.create_draft(db, tenant, key=payload.key, name=payload.name, html_tpl=payload.html_tpl, variables_schema=payload.variables_schema)
    return {"id": str(template.id), "key": template.key, "version": template.version, "status": template.status}


@router.post("/letter-templates/{template_id}/publish")
def publish_letter_template(template_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.edit"))):
    from app.models.core_hr import LetterTemplate

    from app.platform.comms.renderer import TemplateRenderError

    template = db.get(LetterTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Letter template not found")
    try:
        template = letters_service.publish(db, template)
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(template.id), "status": template.status}


class LetterGenerate(BaseModel):
    template_key: str
    context: dict[str, Any] = {}


@router.post("/employees/{employee_id}/letters", status_code=201)
def generate_letter(employee_id: UUID, payload: LetterGenerate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.create"))):
    tenant = require_current_tenant()
    try:
        record = letters_service.generate_letter(db, tenant, employee_id=employee_id, template_key=payload.template_key, context=payload.context, generated_by=current_user.email)
    except letters_service.LetterTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    log_action(db, "employee", employee_id, "letter_generated", current_user.email, {"template_key": payload.template_key})
    return {"id": str(record.id), "verification_token": record.verification_token, "rendered_html": record.rendered_html}


@router.get("/employees/{employee_id}/letters")
def list_letters(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.view"))):
    tenant = require_current_tenant()
    records = letters_service.letter_history(db, tenant, employee_id)
    return [{"id": str(r.id), "template_key": r.template_key, "generated_at": r.generated_at.isoformat() if r.generated_at else None, "verification_token": r.verification_token} for r in records]


@public_router.get("/letters/verify/{token}", response_class=HTMLResponse)
def verify_letter(token: str, db: Session = Depends(get_db)):
    """Public, no-auth -- the "digital verification URL" a printed/emailed letter's
    recipient (or a third party checking authenticity) would open."""
    from app.models.core_hr import LetterRecord

    record = db.query(LetterRecord).filter(LetterRecord.verification_token == token).first()
    if record is None:
        return HTMLResponse("<p>This letter could not be verified -- the link may be incorrect.</p>", status_code=404)
    return HTMLResponse(f"<h1>Letter verified</h1><p>Template: {record.template_key} (v{record.template_version})</p><p>Generated: {record.generated_at}</p>")


# ---- import wizard ----


class ImportBatchCreate(BaseModel):
    entity: str
    rows: list[dict[str, Any]]
    column_mapping: dict[str, str]


@router.post("/import-batches", status_code=201)
def create_import_batch(payload: ImportBatchCreate, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.import.create"))):
    tenant = require_current_tenant()
    try:
        batch = import_wizard.create_batch(db, tenant, entity=payload.entity, rows=payload.rows, column_mapping=payload.column_mapping, created_by=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(batch.id), "status": batch.status, "row_count": batch.row_count, "error_count": batch.error_count}


@router.get("/import-batches/{batch_id}/rows")
def list_import_rows(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.import.view"))):
    from app.models.core_hr import ImportRow

    tenant = require_current_tenant()
    rows = db.query(ImportRow).filter(ImportRow.tenant_id == tenant.tenant_id, ImportRow.batch_id == batch_id).order_by(ImportRow.row_number).all()
    return [{"row_number": r.row_number, "status": r.status, "errors": r.errors_json, "raw": r.raw_json} for r in rows]


@router.post("/import-batches/{batch_id}/dry-run")
def dry_run_import_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.import.create"))):
    tenant = require_current_tenant()
    try:
        batch = import_wizard.mark_dry_run(db, tenant, batch_id)
    except import_wizard.ImportBatchStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": batch.status}


@router.post("/import-batches/{batch_id}/commit")
def commit_import_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.import.create"))):
    tenant = require_current_tenant()
    try:
        result = import_wizard.commit_batch(db, tenant, batch_id, created_by=current_user.email)
    except import_wizard.ImportBatchStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(db, "import_batch", batch_id, "import_committed", current_user.email, result)
    return result


@router.post("/import-batches/{batch_id}/rollback")
def rollback_import_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.import.delete"))):
    tenant = require_current_tenant()
    try:
        deleted = import_wizard.rollback_batch(db, tenant, batch_id)
    except import_wizard.ImportBatchStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(db, "import_batch", batch_id, "import_rolled_back", current_user.email, {"deleted": deleted})
    return {"deleted": deleted}
