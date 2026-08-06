import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError, extract_text
from app.candidates.router import ALLOWED_EXTENSIONS, parse_and_apply_resume
from app.candidates.storage import save_resume_file
from app.core.database import SessionLocal, get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.schemas.public import PublicApplicationSubmitResponse, PublicJobRead

router = APIRouter(prefix="/public", tags=["public"])


def _get_published_job_or_404(db: Session, job_id: uuid.UUID) -> JobRole:
    job = db.get(JobRole, job_id)
    if not job or job.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs", response_model=list[PublicJobRead])
def list_public_jobs(db: Session = Depends(get_db)):
    return (
        db.query(JobRole)
        .filter(JobRole.status == "published")
        .order_by(JobRole.created_at.desc())
        .all()
    )


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
    db: Session = Depends(get_db),
):
    job = _get_published_job_or_404(db, job_id)

    extension = resume.filename.rsplit(".", 1)[-1].lower() if resume.filename and "." in resume.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")

    file_bytes = await resume.read()
    try:
        extract_text(file_bytes, resume.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    resume_path = save_resume_file(file_bytes, extension)

    candidate = Candidate(full_name=full_name, email=email, phone=phone, resume_path=resume_path)
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

    application = Application(job_role_id=job.id, candidate_id=candidate.id, status="received")
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

    background_tasks.add_task(_parse_resume_in_background, candidate.id)

    return PublicApplicationSubmitResponse(application_id=application.id, status=application.status)
