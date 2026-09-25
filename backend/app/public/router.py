import json
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError, extract_text
from app.candidates.router import ALLOWED_EXTENSIONS, parse_and_apply_resume
from app.candidates.storage import save_resume_file
from app.core.database import SessionLocal, get_db
from app.jobs.service import (
    close_job_if_deadline_passed,
    get_application_deadline,
    notify_job_owner_of_new_application,
)
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.recruitment.career_site import CURRENT_CONSENT_VERSION, evaluate_knockout_questions
from app.schemas.public import PublicApplicationSubmitResponse, PublicJobRead

router = APIRouter(prefix="/public", tags=["public"])


def _get_published_job_or_404(db: Session, job_id: uuid.UUID) -> JobRole:
    job = db.get(JobRole, job_id)
    if job:
        close_job_if_deadline_passed(db, job)
    if not job or job.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs", response_model=list[PublicJobRead])
def list_public_jobs(db: Session = Depends(get_db)):
    jobs = db.query(JobRole).filter(JobRole.status == "published").order_by(JobRole.created_at.desc()).all()
    still_published = []
    for job in jobs:
        if not close_job_if_deadline_passed(db, job):
            still_published.append(job)
    return still_published


@router.get("/jobs/{job_id}", response_model=PublicJobRead)
def get_public_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_published_job_or_404(db, job_id)


def _parse_resume_in_background(candidate_id: uuid.UUID) -> None:
    # Runs after the response has already been sent to the applicant, on its own DB
    # session (the request's session is closed by then) -- best-effort, so a parsing
    # failure here can't surface anywhere but the audit log/logs.
    db = SessionLocal()
    try:
        candidate = db.get(Candidate, candidate_id)
        if not candidate:
            return
        try:
            parse_and_apply_resume(db, candidate)
        except Exception:
            pass
    finally:
        db.close()


@router.post("/apply", response_model=PublicApplicationSubmitResponse, status_code=201)
async def submit_application(
    background_tasks: BackgroundTasks,
    job_id: uuid.UUID = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str | None = Form(None),
    resume: UploadFile = File(...),
    consent: bool = Form(...),
    knockout_answers: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # Part 8 section 3 -- DPDP consent capture: refusing to accept an application without
    # consent, rather than accepting it and hoping the checkbox was ticked client-side.
    if not consent:
        raise HTTPException(status_code=400, detail="Consent to data processing is required to apply")

    job = db.get(JobRole, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    close_job_if_deadline_passed(db, job)
    deadline = get_application_deadline(job)
    if deadline is not None and deadline < date.today():
        raise HTTPException(
            status_code=400,
            detail="Applications are no longer being accepted for this job -- the application deadline has passed",
        )
    if job.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")

    extension = resume.filename.rsplit(".", 1)[-1].lower() if resume.filename and "." in resume.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")

    file_bytes = await resume.read()
    try:
        extract_text(file_bytes, resume.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    from app.platform.ops.av_scan import UploadRejectedError, ensure_clean

    try:
        ensure_clean(file_bytes)  # Part 13: AV scan hook (skipped when no scanner is configured)
    except UploadRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resume_path = save_resume_file(file_bytes, extension)

    candidate = Candidate(
        full_name=full_name, email=email, phone=phone, resume_path=resume_path, source="career_portal"
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    log_action(
        db,
        "candidate",
        candidate.id,
        "candidate_uploaded",
        "public",
        {"resume_path": resume_path, "source": "careers_portal"},
    )

    application = Application(
        job_role_id=job.id, candidate_id=candidate.id, status="received",
        consent_given_at=datetime.now(timezone.utc), consent_version=CURRENT_CONSENT_VERSION,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    log_action(
        db,
        "application",
        application.id,
        "application_created",
        "public",
        {"status": application.status, "source": "careers_portal", "job_role_id": str(job.id)},
    )
    # Part 13 section E: the consent ledger entry behind consent_given_at (append-only, tied
    # to the notice version shown, if the tenant has published one).
    from app.platform.tenancy.context import require_current_tenant
    from app.privacy.service import record_consent

    record_consent(db, require_current_tenant(), subject_type="candidate", subject_id=candidate.id, subject_email=email,
                   purpose="recruitment.application", channel="career_site", evidence={"consent_version": CURRENT_CONSENT_VERSION})

    disqualify_reason = None
    if job.knockout_questions_json:
        try:
            answers = json.loads(knockout_answers) if knockout_answers else {}
        except json.JSONDecodeError:
            answers = {}
        disqualify_reason = evaluate_knockout_questions(job.knockout_questions_json, answers)
    if disqualify_reason:
        application.status = "hr_rejected"
        db.commit()
        db.refresh(application)
        log_action(db, "application", application.id, "knockout_disqualified", "public", {"reason": disqualify_reason})
    else:
        notify_job_owner_of_new_application(db, job, candidate)

    background_tasks.add_task(_parse_resume_in_background, candidate.id)

    return PublicApplicationSubmitResponse(application_id=application.id, status=application.status)
