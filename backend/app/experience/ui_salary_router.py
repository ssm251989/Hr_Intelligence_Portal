"""Part 17.8: the Salary page as a queue, plus the candidate's own "Salary & joining details" form.

HR (recruitment.salary.* view via recruitment.application.view):
- GET  /api/v1/ui/salary/queue?state=&job_id=          shortlisted..salary-stage candidates + band check chip
- POST /api/v1/ui/salary/applications/{id}/send-form   email the form link now (or get the link to share)
- PUT  /api/v1/ui/salary/applications/{id}/figures     HR types / corrects the figures -> re-check
- POST /api/v1/ui/salary/applications/{id}/check       re-check against the band now

Public (magic link, no login):
- GET  /api/v1/public/salary-details/{token}            what the form shows (job, company, what's filled)
- POST /api/v1/public/salary-details/{token}            the candidate's answers (one time)
Every query filters on the current company's tenant_id explicitly.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import salary_auto

router = APIRouter(prefix="/api/v1/ui/salary", tags=["ui-salary"])
public_router = APIRouter(prefix="/api/v1/public/salary-details", tags=["salary-form-public"])

QUEUE_STATUSES = ("hr_selected", "interview_scheduled", "interview_selected", "salary_ok", "salary_above_band", "salary_approved", "salary_rejected")
# the chip a person sees
_CHIP = {"waiting": "waiting_for_candidate", "in_band": "in_band", "needs_approval": "needs_approval", "flagged": "flagged", "no_band": "no_band"}


def _need(db, tenant, user, permission: str) -> None:
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


def _app(db, tenant, application_id: UUID) -> Application:
    app = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.id == application_id).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _chip(app: Application) -> str:
    if app.status == "salary_approved":
        return "approved"
    if app.status == "salary_rejected":
        return "declined"
    return _CHIP.get((app.salary_check or {}).get("state") or "waiting", "waiting_for_candidate")


@router.get("/queue")
def salary_queue(state: Optional[str] = None, job_id: Optional[UUID] = None, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    from app.models.iam import ActionToken

    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    q = (db.query(Application, Candidate, JobRole).join(Candidate, Candidate.id == Application.candidate_id)
         .join(JobRole, JobRole.id == Application.job_role_id)
         .filter(Application.tenant_id == tenant.tenant_id, Application.status.in_(QUEUE_STATUSES)))
    if job_id:
        q = q.filter(Application.job_role_id == job_id)
    rows, counts = [], {}
    for app, cand, job in q.order_by(Application.created_at.desc()).limit(500).all():
        if app.salary_check is None:  # first look -> check now so the chip is right
            salary_auto.check(db, tenant, app, job=job, candidate=cand, actor="system")
        chip = _chip(app)
        counts[chip] = counts.get(chip, 0) + 1
        if state and chip != state:
            continue
        form = (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                             ActionToken.entity_id == app.id, ActionToken.action == salary_auto.FORM_ACTION)
                .order_by(ActionToken.created_at.desc()).first())
        check = app.salary_check or {}
        rows.append({
            "application_id": str(app.id), "candidate_id": str(cand.id), "candidate_name": cand.full_name, "job_title": job.title,
            "job_id": str(job.id), "status": app.status, "chip": chip, "check": check,
            "current_ctc": float(cand.current_ctc) if cand.current_ctc is not None else None,
            "expected_ctc": float(app.expected_salary) if app.expected_salary is not None else None,
            "notice_period_days": cand.notice_period_days, "approved_salary": float(app.approved_salary) if app.approved_salary is not None else None,
            "form": None if form is None else {"sent_at": form.created_at.isoformat() if form.created_at else None,
                                               "answered_at": form.responded_at.isoformat() if form.responded_at else None,
                                               "reminded": bool((form.payload_json or {}).get("reminded"))},
        })
    return {"items": rows, "counts": counts, "total": sum(counts.values())}


@router.post("/applications/{application_id}/send-form")
def send_form_now(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.edit")
    return salary_auto.send_form(db, tenant, _app(db, tenant, application_id), actor=current_user.email)


class FiguresIn(BaseModel):
    current_ctc: Optional[float] = Field(None, ge=0)
    expected_ctc: Optional[float] = Field(None, ge=0)
    notice_period_days: Optional[int] = Field(None, ge=0, le=365)
    willing_to_relocate: Optional[bool] = None


@router.put("/applications/{application_id}/figures")
def set_figures(application_id: UUID, payload: FiguresIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.edit")
    app = _app(db, tenant, application_id)
    cand = db.get(Candidate, app.candidate_id)
    figures = payload.model_dump(exclude_unset=True)
    if payload.expected_ctc is not None:
        app.expected_salary = payload.expected_ctc
    salary_auto.take_figures(db, tenant, cand, figures, source=current_user.email, overwrite=True)
    return salary_auto.check(db, tenant, app, candidate=cand, actor=current_user.email)


class DecideIn(BaseModel):
    decision: str
    amount: Optional[float] = Field(None, ge=0, le=1_000_000_000)
    reason: Optional[str] = Field(None, max_length=1000)


@router.post("/applications/{application_id}/decide")
def decide(application_id: UUID, body: DecideIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Part 18.13: HR decides a candidate who needs approval -- approve / counter-offer / reject (reason)."""
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.salary.edit")
    try:
        return salary_auto.decide(db, tenant, _app(db, tenant, application_id), decision=body.decision, actor=current_user.email,
                                  amount=body.amount, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/applications/{application_id}/check")
def recheck(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    return salary_auto.check(db, tenant, _app(db, tenant, application_id), actor=current_user.email)


# ---------------------------------------------------------------- public form

def _resolve(db: Session, token: str):
    from app.platform.iam.action_tokens import ActionTokenError, resolve_action_token

    tenant = require_current_tenant()
    try:
        row = resolve_action_token(db, tenant, token)
    except ActionTokenError as exc:
        raise HTTPException(status_code=410 if str(exc) in ("expired", "already_handled") else 404,
                            detail={"expired": "This link has expired. Please ask the HR team for a new one.",
                                    "already_handled": "Thanks - we already have your answers."}.get(str(exc), "This link isn't valid.")) from exc
    if row.action != salary_auto.FORM_ACTION:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    app = db.get(Application, row.entity_id)
    if app is None:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    return tenant, row, app


@public_router.get("/{token}")
def form_view(token: str, db: Session = Depends(get_db)):
    tenant, _row, app = _resolve(db, token)
    cand = db.get(Candidate, app.candidate_id)
    job = db.get(JobRole, app.job_role_id)
    return {"candidate_first_name": (cand.full_name or "").split(" ")[0] if cand else "", "job_title": job.title if job else "",
            "current_ctc": float(cand.current_ctc) if cand and cand.current_ctc is not None else None,
            "expected_ctc": float(cand.expected_ctc) if cand and cand.expected_ctc is not None else None,
            "notice_period_days": cand.notice_period_days if cand else None,
            "willing_to_relocate": cand.willing_to_relocate if cand else None,
            # Part 18.12: optional asks (Settings > Hiring > Salary)
            "ask_offers": bool(salary_auto._setting(db, tenant, "recruitment.salary.ask_offers")),
            "ask_payslip": bool(salary_auto._setting(db, tenant, "recruitment.salary.ask_payslip")),
            "payslips": len((cand.custom_fields or {}).get("payslips", [])) if cand else 0}


class FormIn(BaseModel):
    current_ctc: float = Field(..., ge=0, le=1_000_000_000)
    expected_ctc: float = Field(..., ge=0, le=1_000_000_000)
    notice_period_days: int = Field(..., ge=0, le=365)
    willing_to_relocate: Optional[bool] = None
    earliest_joining_date: Optional[str] = Field(None, max_length=20)
    offers_in_hand: Optional[int] = Field(None, ge=0, le=20)  # Part 18.12
    best_offer_ctc: Optional[float] = Field(None, ge=0, le=1_000_000_000)


PAYSLIP_TYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}
PAYSLIP_MAX = 5 * 1024 * 1024


@public_router.post("/{token}/payslip")
async def payslip_upload(token: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Part 18.12: optional payslip (PDF/PNG/JPG, 5 MB) -- before the form is sent in. Kept under
    uploads/salary-payslips and listed on the candidate (removed with the candidate, 17.15)."""
    import uuid as _uuid
    from pathlib import Path

    tenant, _row, app = _resolve(db, token)
    ext = PAYSLIP_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="Please upload a PDF, PNG or JPG file.")
    data = await file.read()
    if len(data) > PAYSLIP_MAX:
        raise HTTPException(status_code=400, detail="That file is larger than 5 MB.")
    folder = Path(__file__).resolve().parent.parent.parent / "uploads" / "salary-payslips" / str(tenant.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{_uuid.uuid4()}.{ext}"
    (folder / name).write_bytes(data)
    cand = db.get(Candidate, app.candidate_id)
    fields = dict(cand.custom_fields or {})
    fields["payslips"] = [*fields.get("payslips", []), f"{tenant.tenant_id}/{name}"][-6:]
    cand.custom_fields = fields
    db.commit()
    return {"uploaded": True, "count": len(fields["payslips"])}


@public_router.post("/{token}")
def form_submit(token: str, payload: FormIn, db: Session = Depends(get_db)):
    from app.audit.service import log_action
    from app.platform.iam.action_tokens import mark_action_token_responded

    tenant, row, app = _resolve(db, token)
    cand = db.get(Candidate, app.candidate_id)
    figures = payload.model_dump()
    app.expected_salary = payload.expected_ctc
    salary_auto.take_figures(db, tenant, cand, figures, source="candidate form", overwrite=True)
    extra = {k: v for k, v in (("earliest_joining_date", payload.earliest_joining_date), ("offers_in_hand", payload.offers_in_hand),
                                   ("best_offer_ctc", payload.best_offer_ctc)) if v is not None}
    if extra:
        cand.custom_fields = {**(cand.custom_fields or {}), **extra}
        db.commit()
    mark_action_token_responded(db, row)
    log_action(db, "application", app.id, "salary_form_answered", "candidate", {"fields": list(figures)})
    return {"ok": True}
