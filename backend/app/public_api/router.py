"""Part 30.2c: the public endpoints. Each one calls the service the screen uses -- nothing is re-implemented, the
same rules and the same approval cards apply, and the key acts as its creator (their permissions)."""

import json
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.public_api.base import ApiError, Caller, caller, need_permission

router = APIRouter()
MAX_RESUME = 5 * 1024 * 1024

# what the candidate's status means for the next step (GET /applications/{id})
NEXT_STEP = {
    "received": "Waiting to be screened", "screened": "Waiting for the shortlist decision", "shortlisted": "Interview times are being arranged",
    "hr_selected": "Interview times are being arranged", "interview_scheduled": "Interview booked", "interviewed": "Waiting for the interview decision",
    "salary_pending": "Waiting for the candidate's salary details", "salary_above_band": "Waiting for HR's salary decision",
    "salary_approved": "Waiting for joining documents", "bgv_requested": "Background verification in progress",
    "bgv_pending": "Background verification in progress", "bgv_cleared": "Joining dates and offer next", "offer_sent": "Waiting for the candidate to sign",
    "offer_signed": "Joining", "rejected": "Closed - not selected", "withdrawn": "Closed - the candidate withdrew",
}


def _from_http(exc: HTTPException) -> ApiError:
    detail = exc.detail if isinstance(exc.detail, str) else (exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail))
    return ApiError(exc.status_code, {404: "not_found", 409: "conflict", 403: "forbidden"}.get(exc.status_code, "bad_request"), str(detail))


def _service(fn):
    """A screen function's HTTPException / ValueError -> the API's error shape (status kept)."""
    from app.agents.service import AgentError

    try:
        return fn()
    except ApiError:
        raise
    except HTTPException as exc:
        raise _from_http(exc) from exc
    except PermissionError as exc:
        raise ApiError(403, "forbidden", f"The key's owner is not allowed to do this ({exc}).") from exc
    except (AgentError, ValueError) as exc:
        raise ApiError(409, "conflict", str(exc)) from exc


def _screen_role(c: Caller) -> None:
    if c.user.role not in ("recruiter", "admin"):  # the Jobs / Candidates screens are for recruiters and admins
        raise ApiError(403, "forbidden", "The key's owner must be a recruiter or an admin for this endpoint.")


def _application(db: Session, c: Caller, application_id: UUID):
    from app.models.application import Application

    app = db.get(Application, application_id)
    if app is None or app.tenant_id != c.tenant.tenant_id:
        raise ApiError(404, "not_found", "No application with this id in your company.")
    return app


# ---------------------------------------------------------------- screening


class ScreeningOut(BaseModel):
    score: int = Field(description="0-100: how well the resume fits the JD")
    location_score: Optional[int] = None
    reasons: list[str]
    missing_skills: list[str]
    knockouts: list[dict] = Field(description="the job's knock-out questions (answered when the candidate applies)")


@router.post("/screenings", response_model=ScreeningOut, tags=["screening"], summary="Screen a resume against a JD (nothing is stored)")
async def screen(resume: Optional[UploadFile] = File(None), resume_text: Optional[str] = Form(None, max_length=60000),
                 jd_text: Optional[str] = Form(None, max_length=30000), job_id: Optional[UUID] = Form(None),
                 db: Session = Depends(get_db), c: Caller = Depends(caller("screening"))):
    from app.ai_services.resume_matcher import ResumeMatchError, match_resume
    from app.ai_services.resume_parser import parse_resume
    from app.models.job_role import JobRole
    from app.screening.service import compute_certificates_score, compute_skills_score

    job = None
    if job_id is not None:
        job = db.get(JobRole, job_id)
        if job is None or job.tenant_id != c.tenant.tenant_id or job.deleted_at is not None:
            raise ApiError(404, "not_found", "No job with this id in your company.")
    jd = (jd_text or "").strip() or ((job.jd_text or "").strip() if job else "")
    if len(jd) < 30:
        raise ApiError(422, "invalid", "Send jd_text (at least 30 characters) or the job_id of a job that has a JD.")
    data, name = (await resume.read(), resume.filename or "resume.pdf") if resume is not None else (None, None)
    if data is not None and len(data) > MAX_RESUME:
        raise ApiError(422, "invalid", "The resume file is too big (5 MB at most).")
    if not data and not (resume_text or "").strip():
        raise ApiError(422, "invalid", "Send the resume as a file (resume) or as text (resume_text).")
    try:
        text = (resume_text or "").strip()
        if data:
            from app.candidates.resume_extraction import extract_text

            text = extract_text(data, name) or text
        parsed = parse_resume(text, data, name)
        result = match_resume(jd, parsed, parsed.get("location"), job.location if job else None)
    except ResumeMatchError as exc:
        raise ApiError(502, "ai_failed", f"The AI could not screen this resume: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 -- a parse failure is the caller's file, not our server
        raise ApiError(422, "unreadable_resume", f"The resume could not be read: {type(exc).__name__}") from exc
    reasons = [r for r in [result.get("recommendation")] if r]
    missing: list[str] = []
    if job is not None:
        skills = compute_skills_score(parsed.get("skills"), job.technical_skills_must_have, job.technical_skills_good_to_have,
                                      job.soft_skills_must_have, job.soft_skills_good_to_have, candidate_certificates=parsed.get("certificates"))
        certs = compute_certificates_score(parsed.get("certificates"), job.preferred_certifications)
        missing = list(skills["missing_required"]) + list(skills["missing_preferred"])
        reasons.append(f"Skills match {skills['score']}%" + (f"; missing must-have: {', '.join(skills['missing_required_technical'])}"
                                                               if skills["missing_required_technical"] else ""))
        if certs["missing"]:
            reasons.append(f"Preferred certifications missing: {', '.join(certs['missing'])}")
    return ScreeningOut(score=int(result.get("match_score") or 0), location_score=result.get("location_score"), reasons=reasons,
                        missing_skills=missing, knockouts=list(job.knockout_questions_json or []) if job else [])


# ---------------------------------------------------------------- jobs


class JdDraftIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    department: Optional[str] = None
    location: Optional[str] = None
    key_responsibilities: Optional[str] = Field(None, max_length=5000)
    technical_skills_must_have: list[str] = []
    technical_skills_good_to_have: list[str] = []


@router.post("/jd-drafts", tags=["jobs"], summary="Draft a JD from role inputs (the Job agent's drafting)")
def jd_draft(body: JdDraftIn, db: Session = Depends(get_db), c: Caller = Depends(caller("jobs"))):
    from types import SimpleNamespace

    from app.agents.service import draft_jd_text, job_inputs
    from app.platform.ai import governance

    if not governance.feature_enabled(db, c.tenant, "agents.job"):
        raise ApiError(403, "ai_off", "AI drafting is switched off for your company (AI settings: Job agent).")
    text, log_id = _service(lambda: draft_jd_text(db, c.tenant, job_inputs(SimpleNamespace(**body.model_dump())), feature="agents.job",
                                                  input_refs={"api_key": str(c.key.id)}))
    return {"jd_text": text, "decision_log_id": str(log_id) if log_id else None}


class JobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    department: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[Literal["Full-time", "Part-time", "Contract"]] = None
    positions_count: int = Field(1, ge=1, le=500)
    experience_min_years: Optional[float] = None
    experience_max_years: Optional[float] = None
    technical_skills_must_have: list[str] = []
    technical_skills_good_to_have: list[str] = []
    key_responsibilities: Optional[str] = None
    salary_band_min: Optional[float] = None
    salary_band_max: Optional[float] = None
    hiring_manager_id: Optional[UUID] = None
    jd_text: Optional[str] = None


def _job_out(job) -> dict:
    return {"id": str(job.id), "title": job.title, "status": job.status, "department": job.department, "location": job.location,
            "positions_count": job.positions_count, "has_jd": bool((job.jd_text or "").strip()),
            "published_platforms": job.published_platforms or {}, "created_at": job.created_at.isoformat() if job.created_at else None}


@router.post("/jobs", status_code=201, tags=["jobs"], summary="Create a job (draft). The Job agent then prepares the Publish card; nothing is published by the API")
def create_job(body: JobIn, db: Session = Depends(get_db), c: Caller = Depends(caller("jobs"))):
    from app.jobs.router import create_job as screen_create
    from app.schemas.job import JobRoleCreate

    _screen_role(c)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        payload = JobRoleCreate(**data)
    except Exception as exc:  # noqa: BLE001 -- the screen's own schema rules
        raise ApiError(422, "invalid", str(exc).splitlines()[0][:300]) from exc
    job = _service(lambda: screen_create(payload, db, c.user))
    return _job_out(job)


@router.get("/jobs", tags=["jobs"], summary="List the company's jobs")
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db), c: Caller = Depends(caller("jobs"))):
    from app.models.job_role import JobRole

    q = db.query(JobRole).filter(JobRole.tenant_id == c.tenant.tenant_id, JobRole.deleted_at.is_(None))
    if status:
        q = q.filter(JobRole.status == status)
    return {"items": [_job_out(j) for j in q.order_by(JobRole.created_at.desc()).limit(500).all()]}


@router.get("/jobs/{job_id}", tags=["jobs"], summary="One job")
def get_job(job_id: UUID, db: Session = Depends(get_db), c: Caller = Depends(caller("jobs"))):
    from app.models.job_role import JobRole

    job = db.get(JobRole, job_id)
    if job is None or job.tenant_id != c.tenant.tenant_id or job.deleted_at is not None:
        raise ApiError(404, "not_found", "No job with this id in your company.")
    return {**_job_out(job), "jd_text": job.jd_text, "salary_band": ({"min": job.salary_band_min, "max": job.salary_band_max}
                                                                     if "sensitive" in (c.key.scopes or []) else None)}


# ---------------------------------------------------------------- applications


@router.post("/jobs/{job_id}/applications", status_code=201, tags=["candidates"],
             summary="Apply on the candidate's behalf (same path as the careers page: duplicate block, consent, knock-outs)")
async def apply(job_id: UUID, background_tasks: BackgroundTasks, resume: UploadFile = File(...), full_name: str = Form(..., min_length=2, max_length=200),
                email: str = Form(..., max_length=200), phone: Optional[str] = Form(None), consent: bool = Form(...),
                consent_text: str = Form(..., min_length=10, max_length=2000, description="the consent wording the candidate agreed to"),
                knockout_answers: Optional[str] = Form(None, description='JSON list, e.g. ["Yes", "No"], in the job\'s question order'),
                current_ctc: Optional[float] = Form(None, ge=0), expected_ctc: Optional[float] = Form(None, ge=0),
                notice_period_days: Optional[int] = Form(None, ge=0, le=365), db: Session = Depends(get_db), c: Caller = Depends(caller("candidates"))):
    from app.audit.service import log_action
    from app.public.router import submit_application

    if not consent:
        raise ApiError(422, "consent_required", "The candidate's consent to data processing is required (consent=true and consent_text).")
    if knockout_answers:
        try:
            json.loads(knockout_answers)
        except ValueError as exc:
            raise ApiError(422, "invalid", "knockout_answers must be a JSON list.") from exc
    try:
        out = await submit_application(background_tasks, job_id=job_id, full_name=full_name, email=email, phone=phone, resume=resume, consent=consent,
                                       knockout_answers=knockout_answers, current_ctc=current_ctc, expected_ctc=expected_ctc,
                                       notice_period_days=notice_period_days, db=db)
    except HTTPException as exc:
        if isinstance(exc, ApiError):
            raise
        raise _from_http(exc) from exc
    app_id = out.application_id if hasattr(out, "application_id") else out["application_id"]
    log_action(db, "application", app_id, "api_application_consent", f"api:{c.key.prefix}"[:50], {"consent_text": consent_text, "api_key_id": str(c.key.id)})
    status = out.status if hasattr(out, "status") else out["status"]
    return {"application_id": str(app_id), "status": status}


def _waiting_card(db: Session, c: Caller, app) -> Optional[dict]:
    from app.agents.service import suggestion_to_dict
    from app.models.intelligence import AgentSuggestion

    row = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == c.tenant.tenant_id, AgentSuggestion.entity_id == app.id,
                                            AgentSuggestion.status == "pending").order_by(AgentSuggestion.created_at.desc()).first())
    if row is None:
        return None
    d = suggestion_to_dict(row)
    return {k: d[k] for k in ("id", "kind", "title", "created_at")}


@router.get("/applications/{application_id}", tags=["candidates"], summary="Status, score, next step and the card waiting for HR (if any)")
def get_application(application_id: UUID, db: Session = Depends(get_db), c: Caller = Depends(caller("candidates"))):
    from app.recruitment.scoring import score_round

    app = _application(db, c, application_id)
    return {"id": str(app.id), "job_id": str(app.job_role_id), "candidate_id": str(app.candidate_id), "status": app.status,
            "score": score_round(app.composite_score), "missing_skills": app.missing_skills or [],
            "next_step": NEXT_STEP.get(app.status or "", (app.status or "").replace("_", " ")), "waiting_card": _waiting_card(db, c, app),
            "created_at": app.created_at.isoformat() if getattr(app, "created_at", None) else None}


@router.get("/applications/{application_id}/journey", tags=["candidates"], summary="What the agents did for this candidate, oldest first")
def journey(application_id: UUID, db: Session = Depends(get_db), c: Caller = Depends(caller("candidates"))):
    from app.models.autopilot import AgentActivity

    app = _application(db, c, application_id)
    rows = (db.query(AgentActivity).filter(AgentActivity.tenant_id == c.tenant.tenant_id, AgentActivity.entity_type == "application",
                                           AgentActivity.entity_id == app.id).order_by(AgentActivity.created_at.asc()).limit(200).all())
    return {"items": [{"agent": a.agent, "action": a.action, "outcome": a.outcome, "summary": a.summary,
                       "at": a.created_at.isoformat() if a.created_at else None} for a in rows]}


@router.post("/applications/{application_id}/interview-scheduling", tags=["scheduling"], summary="Send interview times now (= the screen's button)")
def send_interview_times(application_id: UUID, db: Session = Depends(get_db), c: Caller = Depends(caller("scheduling"))):
    from app.interview_scheduling import automation

    app = _application(db, c, application_id)
    need_permission(c, db, "recruitment.interview.edit")
    out = automation.start(db, c.tenant, app, c.user, trigger="send_now", force=True)
    if out.get("outcome") not in ("started", "retrying"):
        raise ApiError(409, "not_started", out.get("reason") or "The interview times could not be sent.")
    return {k: v for k, v in out.items() if isinstance(v, (str, int, float, bool, type(None)))}


# ---------------------------------------------------------------- cards


@router.get("/cards", tags=["cards"], summary="Approval cards this key's owner can decide (the same cards as 'Waiting for you')")
def cards(status: Literal["pending"] = "pending", db: Session = Depends(get_db), c: Caller = Depends(caller("cards"))):
    from app.agents.service import inbox, suggestion_to_dict

    return {"items": [suggestion_to_dict(s) for s in inbox(db, c.tenant, c.user)]}


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    payload: Optional[dict[str, Any]] = Field(None, description="the changed card (action=edit)")


@router.post("/cards/{card_id}/decision", tags=["cards"], summary="Approve, change-and-approve or decline a card (same appliers and reviewer rules as the screen)")
def decide_card(card_id: UUID, body: DecisionIn, db: Session = Depends(get_db), c: Caller = Depends(caller("cards"))):
    from app.agents.service import decide, suggestion_to_dict
    from app.models.intelligence import AgentSuggestion

    s = db.get(AgentSuggestion, card_id)
    if s is None or s.tenant_id != c.tenant.tenant_id:
        raise ApiError(404, "not_found", "No card with this id in your company.")
    if body.action == "edit" and not body.payload:
        raise ApiError(422, "invalid", "action=edit needs the changed card in payload.")

    # decide() refuses before changing anything; each applier rolls back its own step (as on the screen)
    return suggestion_to_dict(_service(lambda: decide(db, c.tenant, s, user=c.user, action=body.action, edited_payload=body.payload)))
