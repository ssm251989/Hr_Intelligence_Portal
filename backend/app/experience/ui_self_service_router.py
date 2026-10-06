"""Part 20.3: employee self-service (app/employees/self_service.py). Every /me route works on the signed-in
person's own employee record only.

Employee:
- GET  /api/v1/ui/self-service/me                              my profile, documents & letters, assets, change requests, exit status
- POST /api/v1/ui/self-service/me/change-requests              {changes, note}  -> HR approves
- POST /api/v1/ui/self-service/me/change-requests/{id}/cancel
- GET  /api/v1/ui/self-service/me/letters/{id}.pdf             one of my letters
- POST /api/v1/ui/self-service/me/resignation/letter           upload my resignation letter (optional)
- POST /api/v1/ui/self-service/me/resignation/withdraw         before HR approves
Manager:
- GET  /api/v1/ui/self-service/team-exits                      resignations waiting for me
- POST /api/v1/ui/self-service/team-exits/{id}/approve         {note}
HR:
- GET  /api/v1/ui/self-service/change-requests?employee_id=    (core_hr.employee.view)
- POST /api/v1/ui/self-service/change-requests/{id}/review     {approve, note} (core_hr.employee.edit)
- GET  /api/v1/ui/self-service/separations/{id}/resignation-letter   (HR or the person's manager)
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.employees import self_service as ss
from app.models.core_hr import Employee, LetterRecord
from app.models.service_desk import Separation
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/self-service", tags=["ui-self-service"])


def _bad(exc: Exception, code: int = 409):
    return HTTPException(status_code=code, detail=str(exc))


def _mine(db: Session, user: User) -> Employee:
    e = ss.me(db, require_current_tenant(), user)
    if e is None:
        raise HTTPException(status_code=404, detail="Your login isn't linked to an employee record yet - ask HR.")
    return e


@router.get("/me")
def my_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ss.my_profile(db, require_current_tenant(), current_user)


class ChangeIn(BaseModel):
    changes: dict = Field(default_factory=dict)
    note: Optional[str] = None


@router.post("/me/change-requests")
def request_change(body: ChangeIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return ss.request_change(db, require_current_tenant(), current_user, body.changes, body.note)
    except ss.SelfServiceError as exc:
        raise _bad(exc, 400) from exc


@router.post("/me/change-requests/{request_id}/cancel")
def cancel_change(request_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return ss.cancel_change(db, require_current_tenant(), current_user, request_id)
    except ss.SelfServiceError as exc:
        raise _bad(exc) from exc


@router.get("/me/letters/{letter_id}.pdf")
def my_letter(letter_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.employees.exit_checklist import letter_pdf

    e = _mine(db, current_user)
    rec = db.get(LetterRecord, letter_id)
    if rec is None or rec.tenant_id != e.tenant_id or rec.employee_id != e.id:
        raise HTTPException(status_code=404, detail="Not found.")
    return Response(letter_pdf(db, rec.id), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{rec.template_key}.pdf"'})


def _open_resignation(db: Session, e: Employee) -> Optional[Separation]:
    return (db.query(Separation).filter(Separation.tenant_id == e.tenant_id, Separation.employee_id == e.id, Separation.status.in_(ss.OPEN))
            .order_by(Separation.created_at.desc()).first())


@router.post("/me/resignation/letter")
async def upload_letter(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.employees.exit_checklist import ChecklistError, save_upload

    e = _mine(db, current_user)
    s = _open_resignation(db, e)
    if s is None:
        raise HTTPException(status_code=404, detail="You don't have a resignation in progress.")
    try:
        s.resignation_letter_ref = save_upload(require_current_tenant(), await file.read(), file.filename or "letter")
    except ChecklistError as exc:
        raise _bad(exc, 400) from exc
    db.commit()
    return {"ok": True, "name": file.filename}


@router.post("/me/resignation/withdraw")
def withdraw(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        s = ss.withdraw_mine(db, require_current_tenant(), current_user)
    except ss.SelfServiceError as exc:
        raise _bad(exc) from exc
    return {"ok": True, "status": s.status}


@router.get("/team-exits")
def team_exits(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"items": ss.team_exits(db, require_current_tenant(), current_user)}


class NoteIn(BaseModel):
    note: Optional[str] = None


@router.post("/team-exits/{separation_id}/approve")
def manager_approve(separation_id: UUID, body: NoteIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    s = db.get(Separation, separation_id)
    if s is None or s.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That exit doesn't exist.")
    try:
        ss.manager_approve(db, tenant, s, current_user, note=body.note)
    except ss.SelfServiceError as exc:
        raise _bad(exc) from exc
    return {"ok": True, "items": ss.team_exits(db, tenant, current_user)}


@router.get("/change-requests")
def change_requests(employee_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    return {"items": ss.pending_requests(db, require_current_tenant(), employee_id)}


class ReviewIn(BaseModel):
    approve: bool
    note: Optional[str] = None


@router.post("/change-requests/{request_id}/review")
def review(request_id: UUID, body: ReviewIn, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    try:
        return ss.review(db, require_current_tenant(), request_id, approve=body.approve, note=body.note, actor=current_user.email)
    except ss.SelfServiceError as exc:
        raise _bad(exc) from exc


@router.get("/separations/{separation_id}/resignation-letter")
def resignation_letter(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.employees.exit_checklist import UPLOADS

    tenant = require_current_tenant()
    s = db.get(Separation, separation_id)
    if s is None or s.tenant_id != tenant.tenant_id or not s.resignation_letter_ref:
        raise HTTPException(status_code=404, detail="Not found.")
    e = db.get(Employee, s.employee_id)
    boss = ss.manager_of(db, e) if e is not None else None
    if not (has_permission(db, tenant, current_user, "separation.case.view") or (boss is not None and boss.id == current_user.id)
            or (e is not None and e.user_id == current_user.id)):
        raise HTTPException(status_code=404, detail="Not found.")
    path = UPLOADS / s.resignation_letter_ref
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


class StartExitIn(BaseModel):
    kind: str
    last_working_day: date
    notes: str
    confirm_now: bool = True
    send_notice: bool = True


@router.post("/employees/{employee_id}/start-exit")
def start_exit(employee_id: UUID, body: StartExitIn, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.create"))):
    """HR: Resigned / Terminated / Absconded / Retirement / Contract end from the Employees list (Part 20.3)."""
    try:
        s = ss.start_exit(db, require_current_tenant(), employee_id, kind=body.kind, last_working_day=body.last_working_day, notes=body.notes,
                          confirm_now=body.confirm_now, send_notice=body.send_notice, actor=current_user.email, actor_user_id=current_user.id)
    except ss.SelfServiceError as exc:
        raise _bad(exc) from exc
    return {"separation_id": str(s.id), "status": s.status}


# ---- Part 20.4: employee as interviewer (app/employees/interviewers.py) ----


@router.get("/employees/{employee_id}/interviewer")
def interviewer_setup(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    from app.employees import interviewers as iv

    tenant = require_current_tenant()
    e = db.get(Employee, employee_id)
    if e is None or e.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That employee doesn't exist.")
    return iv.pools_view(db, tenant, e)


class MakeInterviewerIn(BaseModel):
    pool_ids: list[UUID] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    max_per_day: Optional[int] = None


@router.post("/employees/{employee_id}/make-interviewer")
def make_interviewer(employee_id: UUID, body: MakeInterviewerIn, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    from app.employees import interviewers as iv

    tenant = require_current_tenant()
    e = db.get(Employee, employee_id)
    if e is None or e.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That employee doesn't exist.")
    try:
        return iv.make_interviewer(db, tenant, e, pool_ids=body.pool_ids, skills=[s.strip()[:60] for s in body.skills if s.strip()][:20],
                                   max_per_day=body.max_per_day, actor=current_user.email)
    except iv.InterviewerError as exc:
        raise _bad(exc) from exc


@router.post("/employees/{employee_id}/remove-interviewer")
def remove_interviewer(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    from app.employees import interviewers as iv

    tenant = require_current_tenant()
    e = db.get(Employee, employee_id)
    if e is None or e.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That employee doesn't exist.")
    return iv.remove_interviewer(db, tenant, e, actor=current_user.email)


@router.post("/interviewers/link")
def link_interviewers(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    from app.employees import interviewers as iv

    return iv.link_existing(db, require_current_tenant(), actor=current_user.email)


class LinkIn(BaseModel):
    employee_id: UUID


@router.post("/interviewers/{availability_id}/link")
def link_interviewer(availability_id: UUID, body: LinkIn, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.edit"))):
    from app.employees import interviewers as iv

    try:
        return iv.link_to(db, require_current_tenant(), availability_id, body.employee_id, actor=current_user.email)
    except iv.InterviewerError as exc:
        raise _bad(exc, 404) from exc
