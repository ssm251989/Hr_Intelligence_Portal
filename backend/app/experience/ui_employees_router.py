"""Part 20.1: the Employees tab (always on -- not switched off with the older People module).

- GET    /api/v1/ui/employees                         list (+ filters q / department_id / location_id / status / joined_from / joined_to / role)
- GET    /api/v1/ui/employees/export.xlsx             the same list as Excel (?columns=a,b,c)
- GET    /api/v1/ui/employees/{id}                    profile (Personal / Job / Documents / Assets / History)
- PATCH  /api/v1/ui/employees/{id}                    edit details (the Employee ID never changes)
- POST   /api/v1/ui/employees/{id}/invite             (re)send the app invite;  POST /invites {ids} for several
- GET    /api/v1/ui/employees/assets/in-stock         assets that can be given (works with the Assets module hidden)
- POST   /api/v1/ui/employees/{id}/assets             give an asset (existing one, or a new one registered on the spot)
- POST   /api/v1/ui/employees/{id}/assets/{allocation_id}/return
- GET/PUT /api/v1/ui/employees/settings/id-format     Employee ID format (prefix + padding; the running number carries on)
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.employees import accounts, directory
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/employees", tags=["ui-employees"])
VIEW, EDIT = "core_hr.employee.view", "core_hr.employee.edit"


def _emp(db: Session, employee_id: UUID):
    e = directory.employee_or_none(db, require_current_tenant(), employee_id)
    if e is None:
        raise HTTPException(status_code=404, detail="That employee doesn't exist.")
    return e


def _test_mode(db: Session) -> bool:
    try:
        from app.employees import mailboxes

        return mailboxes.active_provider(db, require_current_tenant()) == "test"
    except Exception:  # noqa: BLE001 -- before 20.2b there is no provider yet
        return False


@router.get("")
def list_employees(q: Optional[str] = None, department_id: Optional[str] = None, location_id: Optional[str] = None, status: Optional[str] = None,
                   joined_from: Optional[date] = None, joined_to: Optional[date] = None, role: Optional[str] = None,
                   db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    tenant = require_current_tenant()
    items = directory.rows(db, tenant, q=q, department_id=department_id, location_id=location_id, status=status,
                           joined_from=joined_from, joined_to=joined_to, role=role)
    from app.platform.iam.authz import has_permission

    return {"items": items, "facets": directory.facets(db, tenant), "test_mode": _test_mode(db),
            "can_edit": has_permission(db, tenant, current_user, EDIT)}


@router.get("/export.xlsx")
def export(q: Optional[str] = None, department_id: Optional[str] = None, location_id: Optional[str] = None, status: Optional[str] = None,
           joined_from: Optional[date] = None, joined_to: Optional[date] = None, role: Optional[str] = None, columns: Optional[str] = None,
           db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    tenant = require_current_tenant()
    items = directory.rows(db, tenant, q=q, department_id=department_id, location_id=location_id, status=status,
                           joined_from=joined_from, joined_to=joined_to, role=role)
    data = directory.export_xlsx(items, columns.split(",") if columns else None)
    log_action(db, "employee", None, "employees_exported", current_user.email[:50], {"rows": len(items)})
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="employees-{date.today().isoformat()}.xlsx"'})


@router.get("/settings/id-format")
def get_id_format(db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    return directory.id_format(db, require_current_tenant())


class IdFormatIn(BaseModel):
    prefix: str = Field("", max_length=12)
    padding: int = 4


@router.put("/settings/id-format")
def put_id_format(body: IdFormatIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return directory.set_id_format(db, require_current_tenant(), prefix=body.prefix, padding=body.padding, actor=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/assets/in-stock")
def in_stock(category: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    from app.models.service_desk import Asset

    tenant = require_current_tenant()
    query = db.query(Asset).filter(Asset.tenant_id == tenant.tenant_id, Asset.status == "in_stock")
    if category:
        query = query.filter(Asset.category_code == category)
    return [{"id": str(a.id), "tag": a.asset_tag, "name": a.name, "category_code": a.category_code} for a in query.order_by(Asset.asset_tag).limit(200)]


class InvitesIn(BaseModel):
    ids: list[UUID]


@router.post("/invites")
def bulk_invites(body: InvitesIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    tenant = require_current_tenant()
    out = []
    for employee_id in body.ids[:200]:
        e = directory.employee_or_none(db, tenant, employee_id)
        if e is None:
            continue
        try:
            out.append({"id": str(e.id), "name": directory.name_of(e), **accounts.send_invite(db, tenant, e, actor=current_user.email)})
        except ValueError as exc:
            out.append({"id": str(e.id), "name": directory.name_of(e), "error": str(exc)})
    return {"results": out}


# ---- Part 20.2: the Onboarding agent's approval cards + IT to-dos ----


def _card(db: Session, card_id: UUID):
    from app.models.intelligence import AgentSuggestion

    s = db.get(AgentSuggestion, card_id)
    if s is None or s.tenant_id != require_current_tenant().tenant_id or s.kind not in ("employee_create", "it_mailbox_create", "it_mailbox_suspend"):
        raise HTTPException(status_code=404, detail="That card no longer exists.")
    return s


@router.get("/agent/pending")
def agent_pending(db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    from app.employees import creation

    tenant = require_current_tenant()
    return {"cards": creation.pending(db, tenant), "it_todos": creation.it_todos(db, tenant)}


@router.get("/agent/by-case/{case_id}")
def agent_by_case(case_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    from app.employees import creation
    from app.models.intelligence import AgentSuggestion

    s = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == require_current_tenant().tenant_id, AgentSuggestion.kind == creation.KIND,
                                          AgentSuggestion.entity_id == case_id).order_by(AgentSuggestion.created_at.desc()).first())
    return creation.to_dict(s) if s is not None else None


class ApproveIn(BaseModel):
    edits: dict = Field(default_factory=dict)


@router.post("/agent/{card_id}/approve")
def agent_approve(card_id: UUID, body: ApproveIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    """Approve (or Retry after a failed step). The provider's one-time password, if any, is in this
    response only -- shown to HR once, never stored."""
    from app.employees import creation

    try:
        return creation.approve(db, require_current_tenant(), _card(db, card_id), edits=body.edits, actor=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class NoteIn(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


@router.post("/agent/{card_id}/reject")
def agent_reject(card_id: UUID, body: NoteIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    from app.employees import creation

    return creation.reject(db, require_current_tenant(), _card(db, card_id), actor=current_user.email, note=body.note)


@router.post("/agent/{card_id}/refresh")
def agent_refresh(card_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    """Prepare the card again (e.g. after the joiner changed their details)."""
    from app.employees import creation
    from app.models.onboarding import PreboardingCase

    s = _card(db, card_id)
    case = db.get(PreboardingCase, s.entity_id)
    if case is None:
        raise HTTPException(status_code=404, detail="The joiner no longer exists.")
    return creation.to_dict(creation.prepare(db, require_current_tenant(), case, actor=current_user.email))


class EmailCheckIn(BaseModel):
    address: str = Field(..., max_length=200)
    employee_id: Optional[UUID] = None


@router.post("/email/check")
def email_check(body: EmailCheckIn, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    from app.employees import mailboxes

    ok, why = mailboxes.is_free(db, require_current_tenant(), body.address, except_employee_id=body.employee_id)
    return {"address": body.address.strip().lower(), "free": ok, "why": why or None}


class ItDoneIn(BaseModel):
    address: Optional[str] = Field(None, max_length=200)


@router.post("/it-todos/{card_id}/done")
def it_done(card_id: UUID, body: ItDoneIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    """"Done - mailbox created" (IT/HR confirms the address). The app login moves to it and a fresh invite goes there."""
    from app.employees import mailboxes
    from app.models.core_hr import Employee

    tenant = require_current_tenant()
    s = _card(db, card_id)
    try:
        out = mailboxes.confirm_it_todo(db, tenant, s, address=body.address, actor=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if s.kind == "it_mailbox_create":
        e = db.get(Employee, s.entity_id)
        if e is not None and e.status in ("active", "on_notice"):
            try:
                out["invite"] = accounts.send_invite(db, tenant, e, actor=current_user.email)
            except ValueError as exc:
                out["invite_error"] = str(exc)
    return out


@router.get("/{employee_id}")
def get_profile(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    from app.platform.iam.authz import has_permission

    tenant = require_current_tenant()
    return {**directory.profile(db, tenant, _emp(db, employee_id)), "can_edit": has_permission(db, tenant, current_user, EDIT),
            "test_mode": _test_mode(db)}


class EmployeeEdit(BaseModel):
    first_name: Optional[str] = Field(None, max_length=120)
    last_name: Optional[str] = Field(None, max_length=120)
    preferred_name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=40)
    personal_email: Optional[str] = Field(None, max_length=200)
    designation: Optional[str] = Field(None, max_length=120)
    department_id: Optional[str] = None
    location_id: Optional[str] = None
    manager_id: Optional[str] = None
    employment_type: Optional[str] = Field(None, max_length=30)
    joined_on: Optional[date] = None
    previous_experience_months: Optional[int] = Field(None, ge=0, le=600)
    rehire_eligible: Optional[bool] = None


@router.patch("/{employee_id}")
def edit_employee(employee_id: UUID, body: EmployeeEdit, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    """Corrections to the details (logged with before/after). The Employee ID can't be changed."""
    from app.models.core_hr import EmploymentRecord

    tenant = require_current_tenant()
    e = _emp(db, employee_id)
    data = body.model_dump(exclude_unset=True)
    before, after = {}, {}
    person = {"first_name": "first_name", "last_name": "last_name", "preferred_name": "preferred_name", "phone": "personal_phone",
              "personal_email": "personal_email", "joined_on": "joined_on", "previous_experience_months": "previous_experience_months",
              "rehire_eligible": "rehire_eligible"}
    for key, attr in person.items():
        if key in data and getattr(e, attr) != data[key]:
            if key == "first_name" and not (data[key] or "").strip():
                raise HTTPException(status_code=400, detail="First name can't be empty.")
            before[key], after[key] = str(getattr(e, attr)) if getattr(e, attr) is not None else None, data[key]
            setattr(e, attr, data[key])
    job = {k: data[k] for k in ("designation", "department_id", "location_id", "manager_id", "employment_type") if k in data}
    if job:
        if job.get("manager_id") == str(e.id):
            raise HTTPException(status_code=400, detail="Someone can't be their own manager.")
        r = directory.current_record(db, e.id)
        if r is None:
            r = EmploymentRecord(tenant_id=tenant.tenant_id, employee_id=e.id, effective_from=e.joined_on or date.today(), event_type="hire",
                                 created_by=current_user.email[:50])
            db.add(r)
        for key, value in job.items():
            attr = "manager_employee_id" if key == "manager_id" else key
            value = (UUID(value) if value else None) if key in ("department_id", "location_id", "manager_id") else (value or None)
            if getattr(r, attr) != value:
                before[key], after[key] = str(getattr(r, attr)) if getattr(r, attr) is not None else None, str(value) if value is not None else None
                setattr(r, attr, value)
    db.commit()
    if after:
        log_action(db, "employee", e.id, "employee_details_corrected", current_user.email[:50], {"before": before, "after": after})
    return directory.profile(db, tenant, e)


@router.post("/{employee_id}/invite")
def invite(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    try:
        return accounts.send_invite(db, require_current_tenant(), _emp(db, employee_id), actor=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class GiveAssetIn(BaseModel):
    asset_id: Optional[UUID] = None
    category_code: Optional[str] = None
    asset_tag: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)
    serial_number: Optional[str] = Field(None, max_length=200)


@router.post("/{employee_id}/assets", status_code=201)
def give_asset(employee_id: UUID, body: GiveAssetIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    """Give an asset from the Employee list / profile -- works with the Assets module hidden."""
    from app.models.service_desk import Asset
    from app.service_desk import assets as svc

    tenant = require_current_tenant()
    e = _emp(db, employee_id)
    try:
        if body.asset_id:
            asset = db.get(Asset, body.asset_id)
            if asset is None or asset.tenant_id != tenant.tenant_id:
                raise HTTPException(status_code=404, detail="That asset doesn't exist.")
        else:
            if not (body.category_code and (body.asset_tag or "").strip() and (body.name or "").strip()):
                raise HTTPException(status_code=400, detail="Pick an asset, or give the type, tag and name of a new one.")
            if db.query(Asset.id).filter(Asset.tenant_id == tenant.tenant_id, Asset.asset_tag == body.asset_tag.strip()).first():
                raise HTTPException(status_code=409, detail=f"An asset with tag {body.asset_tag.strip()} already exists.")
            asset = svc.register_asset(db, tenant, asset_tag=body.asset_tag.strip(), category_code=body.category_code, name=body.name.strip(),
                                       serial_number=(body.serial_number or "").strip() or None)
        allocation = svc.allocate(db, tenant, asset, employee_id=e.id, actor=current_user.email)
    except svc.AssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, "employee", e.id, "asset_given", current_user.email[:50], {"asset": asset.asset_tag, "name": asset.name})
    return {"allocation_id": str(allocation.id), "asset_id": str(asset.id), "tag": asset.asset_tag, "name": asset.name}


class ReturnIn(BaseModel):
    condition: str = "good"
    notes: Optional[str] = Field(None, max_length=500)


@router.post("/{employee_id}/assets/{allocation_id}/return")
def return_asset(employee_id: UUID, allocation_id: UUID, body: ReturnIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    from app.models.service_desk import AssetAllocation
    from app.service_desk import assets as svc

    tenant = require_current_tenant()
    e = _emp(db, employee_id)
    al = db.get(AssetAllocation, allocation_id)
    if al is None or al.employee_id != e.id:
        raise HTTPException(status_code=404, detail="That asset isn't with this person.")
    if al.returned_at is not None:
        raise HTTPException(status_code=409, detail="That asset was already returned.")
    try:
        svc.return_asset(db, tenant, al, condition=body.condition if body.condition in ("good", "damaged", "lost") else "good",
                         received_by=current_user.email, notes=body.notes)
    except svc.AssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, "employee", e.id, "asset_returned", current_user.email[:50], {"allocation_id": str(al.id), "condition": body.condition})
    return {"ok": True}
