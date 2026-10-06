"""Fix 2026-10-06: exit interview -- answered by the employee, read by HR (app/employees/exit_interview.py).

Employee (own data only):
- GET  /api/v1/ui/exit-interview/me                 questions + my answers + status + deadline
- PUT  /api/v1/ui/exit-interview/me                 autosave a draft            {answers}
- POST /api/v1/ui/exit-interview/me/submit          submit (then read-only)     {answers}
HR (separation_hr.exit_interview.view / .edit -- NOT managers):
- GET  /api/v1/ui/exit-interview/separations/{id}   read-only card: status, answers, AI summary, HR notes
- POST /api/v1/ui/exit-interview/separations/{id}/remind
- PUT  /api/v1/ui/exit-interview/separations/{id}/notes        {notes}  (private)
- POST /api/v1/ui/exit-interview/separations/{id}/record-call  {answers} only when the person can't answer
- POST /api/v1/ui/exit-interview/separations/{id}/summary      make the AI summary again
- GET  /api/v1/ui/exit-interview/report             totals by department / manager / tenure band (no individual answers)
Settings (platform.settings.configure): GET/PUT /api/v1/ui/exit-interview/settings
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.employees import exit_interview as ei
from app.models.core_hr import Employee
from app.models.service_desk import Separation
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/exit-interview", tags=["ui-exit-interview"])
VIEW, EDIT = "separation_hr.exit_interview.view", "separation_hr.exit_interview.edit"


def _mine(db: Session, user: User) -> Separation:
    tenant = require_current_tenant()
    me = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()
    s = (db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == me.id)
         .order_by(Separation.created_at.desc()).first()) if me is not None else None
    if s is None or s.status == "withdrawn":
        raise HTTPException(status_code=404, detail="You don't have an exit in progress.")
    return s


def _sep(db: Session, separation_id: UUID) -> Separation:
    s = db.get(Separation, separation_id)
    if s is None or s.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="That exit doesn't exist.")
    return s


class AnswersIn(BaseModel):
    answers: dict = Field(default_factory=dict)


def _bad(exc: Exception):
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/me")
def my_interview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ei.employee_view(db, require_current_tenant(), _mine(db, current_user))


@router.put("/me")
def my_draft(body: AnswersIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return ei.save_draft(db, require_current_tenant(), _mine(db, current_user), body.answers, actor=current_user.email)
    except ei.ExitInterviewError as exc:
        raise _bad(exc) from exc


@router.post("/me/submit")
def my_submit(body: AnswersIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return ei.submit(db, require_current_tenant(), _mine(db, current_user), body.answers, actor=current_user.email)
    except ei.ExitInterviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/separations/{separation_id}")
def hr_card(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    return ei.hr_view(db, require_current_tenant(), _sep(db, separation_id))


@router.post("/separations/{separation_id}/remind")
def hr_remind(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    try:
        return ei.send_reminder(db, require_current_tenant(), _sep(db, separation_id), actor=current_user.email)
    except ei.ExitInterviewError as exc:
        raise _bad(exc) from exc


class NotesIn(BaseModel):
    notes: Optional[str] = Field(None, max_length=5000)


@router.put("/separations/{separation_id}/notes")
def hr_notes(separation_id: UUID, body: NotesIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    s = _sep(db, separation_id)
    ei.set_notes(db, s, body.notes or "", actor=current_user.email)
    return ei.hr_view(db, require_current_tenant(), s)


@router.post("/separations/{separation_id}/record-call")
def hr_record_call(separation_id: UUID, body: AnswersIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    try:
        return ei.record_from_call(db, require_current_tenant(), _sep(db, separation_id), body.answers, actor=current_user.email)
    except ei.ExitInterviewError as exc:
        raise _bad(exc) from exc


@router.post("/separations/{separation_id}/summary")
def hr_summary(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    s = _sep(db, separation_id)
    if ei.status_of(s) != "submitted":
        raise HTTPException(status_code=409, detail="The summary is made once the answers are submitted.")
    ei.summarize(db, require_current_tenant(), s)
    return ei.hr_view(db, require_current_tenant(), s)


@router.get("/report")
def hr_report(db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    return ei.report(db, require_current_tenant())


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    return ei.config(db, require_current_tenant())


class SettingsIn(BaseModel):
    questions: list[dict]
    ai_summary: bool = True
    reminder_days: int = 3


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    return ei.save_config(db, require_current_tenant(), body.model_dump(), actor=current_user.email)
