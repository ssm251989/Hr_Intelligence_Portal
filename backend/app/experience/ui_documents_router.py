"""Part 18.16/18.17 API: joining documents.

Candidate (no login, the emailed link):
- GET  /api/v1/public/documents/{token}                what is needed + what was received (and why something is asked again)
- POST /api/v1/public/documents/{token}/files/{code}   upload one file (checked by the agent straight away)
- POST /api/v1/public/documents/{token}/submit         "I'm done" -> HR is told
HR:
- GET  /api/v1/ui/documents/{application_id}           review table: every document, the agent's green/amber/red + reasons
- GET  /api/v1/ui/documents/file/{doc_id}              open one file
- POST /api/v1/ui/documents/{application_id}/approve   {doc_ids?} (none = all pending); all approved -> BGV
- POST /api/v1/ui/documents/{application_id}/reupload  {codes, note} -> the candidate is emailed the list
- POST /api/v1/ui/documents/{application_id}/send-form send (or resend) the upload link
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import joining_docs as jd

router = APIRouter(prefix="/api/v1/ui/documents", tags=["ui-documents"])
public_router = APIRouter(prefix="/api/v1/public/documents", tags=["documents-public"])


def _resolve(db: Session, token: str):
    """A document link stays usable after "submit" (re-uploads reuse it) until it expires or is withdrawn."""
    from datetime import datetime, timezone

    from app.models.iam import ActionToken

    tenant = require_current_tenant()
    row = db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.token == token).first()
    if row is None or row.invalidated_at is not None:
        raise HTTPException(status_code=404, detail="This link isn't valid any more.")
    if row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This link has expired. Please ask the HR team for a new one.")
    if row.action != jd.FORM_ACTION:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    app = db.get(Application, row.entity_id)
    if app is None:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    return tenant, row, app


@public_router.get("/{token}")
def form_view(token: str, db: Session = Depends(get_db)):
    tenant, row, app = _resolve(db, token)
    cand = db.get(Candidate, app.candidate_id)
    job = db.get(JobRole, app.job_role_id)
    st = jd.status(db, tenant, app)
    items = [{k: i[k] for k in ("code", "label", "required", "types", "max_mb", "received", "reupload_note")} | {"files": len(i["files"])} for i in st["items"]]
    return {"candidate_first_name": (cand.full_name or "").replace("Demo - ", "").split(" ")[0] if cand else "", "job_title": job.title if job else "",
            "items": items, "missing": st["missing"], "submitted": row.responded_at is not None}


@public_router.post("/{token}/files/{code}")
async def upload(token: str, code: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    tenant, _row, app = _resolve(db, token)
    data = await file.read()
    try:
        doc = jd.save_upload(db, tenant, app, code, file.filename or "file", file.content_type or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"uploaded": True, "code": code, "id": str(doc.id)}


@public_router.post("/{token}/submit")
def submit(token: str, db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    from app.models.comms import OutboundMessage

    tenant, row, app = _resolve(db, token)
    st = jd.status(db, tenant, app)
    if st["missing"]:
        raise HTTPException(status_code=400, detail="Some required documents are still missing.")
    row.responded_at = datetime.now(timezone.utc)
    cand = db.get(Candidate, app.candidate_id)
    job = db.get(JobRole, app.job_role_id)
    for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.id.in_([i for i in (job.created_by, job.hiring_manager_id) if i] or [None])):
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.documents", to_addresses=[u.email],
                               subject=f"{cand.full_name if cand else 'A candidate'} sent the joining documents for {job.title} "
                                       f"({st['reds']} need a look, {st['ambers']} to check).",
                               body_ref="/bgv", status="sent", related_entity_type="application", related_entity_id=app.id))
    db.commit()
    log_action(db, "application", app.id, "documents_submitted", "candidate", {"reds": st["reds"], "ambers": st["ambers"]})
    return {"ok": True}


# ---------------------------------------------------------------- HR

def _need(db, user, perm):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, perm):
        raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return tenant


def _app(db, tenant, application_id):
    a = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.id == application_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


@router.get("/file/{doc_id}")
def open_file(doc_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.bgv.view")
    d = db.query(CandidateDocument).filter(CandidateDocument.tenant_id == tenant.tenant_id, CandidateDocument.id == doc_id).first()
    path = jd.UPLOAD_DIR / d.file_path if d else None
    if d is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type=d.content_type, filename=d.original_name or path.name)


@router.get("/{application_id}")
def review(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.bgv.view")
    app = _app(db, tenant, application_id)
    return {**jd.status(db, tenant, app), "cross_checks": jd.cross_check(db, tenant, app), "status": app.status}


class ApproveIn(BaseModel):
    doc_ids: Optional[list[UUID]] = None


@router.post("/{application_id}/approve")
def approve(application_id: UUID, body: ApproveIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.bgv.edit")
    return jd.approve(db, tenant, _app(db, tenant, application_id), actor=current_user.email, doc_ids=[str(i) for i in body.doc_ids or []] or None)


class ReuploadIn(BaseModel):
    codes: list[str]
    note: Optional[str] = Field(None, max_length=1000)


@router.post("/{application_id}/reupload")
def reupload(application_id: UUID, body: ReuploadIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.bgv.edit")
    try:
        return jd.request_reupload(db, tenant, _app(db, tenant, application_id), actor=current_user.email, codes=body.codes, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{application_id}/send-form")
def send_form(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.bgv.edit")
    return jd.send_form(db, tenant, _app(db, tenant, application_id), actor=current_user.email)


# ---------------------------------------------------------------- Part 18.18: BGV decision by HR

bgv_router = APIRouter(prefix="/api/v1/ui/bgv", tags=["ui-bgv-decision"])


class BgvDecideIn(BaseModel):
    decision: str
    note: Optional[str] = Field(None, max_length=1000)
    reason: Optional[str] = Field(None, max_length=1000)
    message: Optional[str] = Field(None, max_length=5000)
    codes: Optional[list[str]] = None


@bgv_router.get("/{application_id}/failed-preview")
def bgv_failed_preview(application_id: UUID, reason: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.recruitment.bgv_decision import preview_failed

    tenant = _need(db, current_user, "recruitment.bgv.edit")
    return preview_failed(db, tenant, _app(db, tenant, application_id), reason or "...")


@bgv_router.post("/{application_id}/decide")
def bgv_decide(application_id: UUID, body: BgvDecideIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.recruitment.bgv_decision import decide

    tenant = _need(db, current_user, "recruitment.bgv.edit")
    try:
        return decide(db, tenant, _app(db, tenant, application_id), decision=body.decision, actor=current_user.email, note=body.note,
                      reason=body.reason, message=body.message, codes=body.codes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- Part 18.19: joining date

joining_router = APIRouter(prefix="/api/v1/ui/joining", tags=["ui-joining"])
joining_public_router = APIRouter(prefix="/api/v1/public/joining", tags=["joining-public"])


class ProposeIn(BaseModel):
    dates: list[str]
    note: Optional[str] = Field(None, max_length=500)


@joining_router.get("/{application_id}")
def joining_info(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.recruitment.joining_dates import info

    tenant = _need(db, current_user, "recruitment.offer.view")
    app = _app(db, tenant, application_id)
    return {"status": app.status, **info(app)}


@joining_router.post("/{application_id}/propose")
def joining_propose(application_id: UUID, body: ProposeIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.recruitment.joining_dates import propose

    tenant = _need(db, current_user, "recruitment.offer.edit")
    try:
        return propose(db, tenant, _app(db, tenant, application_id), body.dates, actor=current_user.email, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _joining_token(db, token):
    from datetime import datetime, timezone

    from app.models.iam import ActionToken
    from app.recruitment.joining_dates import ACTION

    tenant = require_current_tenant()
    row = db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.token == token, ActionToken.action == ACTION).first()
    if row is None or row.invalidated_at is not None:
        raise HTTPException(status_code=404, detail="This link isn't valid any more - HR may have sent new dates.")
    if row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This link has expired. Please ask the HR team for new dates.")
    app = db.get(Application, row.entity_id)
    if app is None:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    return tenant, row, app


@joining_public_router.get("/{token}")
def joining_public_view(token: str, db: Session = Depends(get_db)):
    from app.recruitment.joining_dates import info

    _tenant, row, app = _joining_token(db, token)
    cand = db.get(Candidate, app.candidate_id)
    job = db.get(JobRole, app.job_role_id)
    data = info(app)
    return {"candidate_first_name": (cand.full_name or "").replace("Demo - ", "").split(" ")[0] if cand else "", "job_title": job.title if job else "",
            "dates": data.get("proposed", []), "chosen": data.get("chosen"), "note": data.get("note")}


class ChooseIn(BaseModel):
    date: str


@joining_public_router.post("/{token}")
def joining_public_choose(token: str, body: ChooseIn, db: Session = Depends(get_db)):
    from app.recruitment.joining_dates import choose

    tenant, row, app = _joining_token(db, token)
    if row.responded_at is not None:
        raise HTTPException(status_code=409, detail="You have already chosen a date. Please reply to the HR email to change it.")
    try:
        return choose(db, tenant, row, app, body.date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
