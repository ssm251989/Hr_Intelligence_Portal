import csv
import io
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai_services.resume_parser import ResumeParsingError, parse_resume
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.resume_extraction import (
    ResumeExtractionError,
    UnsupportedFileTypeError,
    extract_text,
)
from app.candidates.storage import resolve_resume_path, save_resume_file
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.candidate import CandidateRead
from app.schemas.candidates_dashboard import (
    CandidateApplicationRow,
    CandidatesListPage,
    CsvImportRowError,
    CsvImportSummary,
)

router = APIRouter(prefix="/candidates", tags=["candidates"])

ALLOWED_EXTENSIONS = {"pdf", "docx"}
CSV_MAX_ROWS = 2000


class NoResumeUploadedError(Exception):
    """Raised when a candidate has no resume_path to parse."""


class ResumeFileMissingError(Exception):
    """Raised when a candidate's resume_path doesn't resolve to a file on disk."""


def _get_candidate_or_404(db: Session, candidate_id: uuid.UUID) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def parse_and_apply_resume(db: Session, candidate: Candidate) -> dict:
    """Extract text from a candidate's uploaded resume, AI-parse it, and apply the
    result onto the candidate record. Shared by the authenticated parse-resume endpoint
    and the public careers portal's background parsing after a direct application.
    """
    if not candidate.resume_path:
        raise NoResumeUploadedError("No resume uploaded for this candidate")

    file_path = resolve_resume_path(candidate.resume_path)
    if not file_path.exists():
        raise ResumeFileMissingError("Resume file missing on disk")

    raw_text = extract_text(file_path.read_bytes(), file_path.name)
    result = parse_resume(raw_text)

    log_action(db, "candidate", candidate.id, "ai_resume_parser_scored", "system", result)
    candidate.parsed_fields = result
    candidate.full_name = result.get("full_name") or candidate.full_name
    candidate.email = result.get("email") or candidate.email
    candidate.phone = result.get("phone") or candidate.phone
    db.commit()
    db.refresh(candidate)
    return result


@router.post("/upload", response_model=CandidateRead, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")

    file_bytes = await file.read()

    try:
        extract_text(file_bytes, file.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    resume_path = save_resume_file(file_bytes, extension)

    candidate = Candidate(resume_path=resume_path, source="manual")
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    log_action(db, "candidate", candidate.id, "candidate_uploaded", "system", {"resume_path": resume_path})
    return candidate


@router.get("", response_model=list[CandidateRead])
def list_candidates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Candidate).order_by(Candidate.created_at.desc()).all()


def _row_to_item(application: Application, candidate: Candidate, job_title: str) -> CandidateApplicationRow:
    experience_years = None
    if candidate.parsed_fields:
        experience_years = candidate.parsed_fields.get("total_experience_years")
    return CandidateApplicationRow(
        application_id=application.id,
        candidate_id=candidate.id,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        job_role_id=application.job_role_id,
        job_title=job_title,
        status=application.status,
        source=candidate.source,
        location=candidate.location,
        applied_on=application.created_at,
        match_score=float(application.match_score) if application.match_score is not None else None,
        experience_years=float(experience_years) if experience_years is not None else None,
        resume_path=candidate.resume_path,
    )


# NOTE: registered before the "/{candidate_id}" routes below -- FastAPI/Starlette match
# routes in registration order using the default string convertor for un-annotated path
# segments, so a literal path like "/applications" or "/import-csv" registered *after*
# "/{candidate_id}" would be swallowed by that param route first (and 422 trying to parse
# "applications" as a UUID) rather than ever reaching this handler.
@router.get("/applications", response_model=CandidatesListPage)
def list_candidate_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    search: Optional[str] = Query(None, description="Matches candidate name or email"),
    job_role_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per (candidate, application) pairing -- the data source for the Candidates
    List page. A candidate who applied to multiple jobs appears once per job, since Job
    Applied/Stage/Match Score are all per-application concepts."""
    query = (
        db.query(Application, Candidate, JobRole.title)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
    )
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    if status is not None:
        query = query.filter(Application.status == status)
    if source is not None:
        query = query.filter(Candidate.source == source)
    if location is not None:
        query = query.filter(Candidate.location.ilike(f"%{location}%"))
    if search is not None:
        query = query.filter(
            or_(Candidate.full_name.ilike(f"%{search}%"), Candidate.email.ilike(f"%{search}%"))
        )

    total = query.count()
    rows = (
        query.order_by(Application.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_row_to_item(application, candidate, title) for application, candidate, title in rows]
    return CandidatesListPage(total=total, page=page, page_size=page_size, items=items)


_CSV_COLUMN_ALIASES = {
    "name": "name",
    "full_name": "name",
    "fullname": "name",
    "candidate_name": "name",
    "email": "email",
    "email_address": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "resume": "resume",
    "resume_link": "resume",
    "resume_url": "resume",
    "resume_path": "resume",
}


def _normalize_csv_row(raw_row: dict) -> dict:
    normalized: dict = {}
    for key, value in raw_row.items():
        if key is None:
            continue
        alias_key = key.strip().lower().replace(" ", "_")
        field = _CSV_COLUMN_ALIASES.get(alias_key)
        if field:
            normalized[field] = (value or "").strip()
    return normalized


@router.post("/import-csv", response_model=CsvImportSummary, status_code=201)
async def import_candidates_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    """Bulk-creates real Candidate rows from a CSV (name, email, phone, resume link are
    the recognized columns; header names are matched case-insensitively). Never reads an
    arbitrary server filesystem path from the file -- a 'resume' column is only honored
    when it's an http(s) URL, since a bare filename in someone's CSV can't refer to
    anything meaningful on the server. Every row either becomes a candidate or is recorded
    in the returned summary with a reason; nothing is silently dropped."""
    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if extension != "csv":
        raise HTTPException(status_code=400, detail="Only .csv files are supported")

    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Could not read CSV file (expected UTF-8 encoding)") from exc

    reader = list(csv.DictReader(io.StringIO(text)))
    if len(reader) > CSV_MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"CSV has too many rows (max {CSV_MAX_ROWS})")

    seen_emails: set[str] = set()
    imported_ids: list[uuid.UUID] = []
    errors: list[CsvImportRowError] = []

    for index, raw_row in enumerate(reader, start=1):
        row = _normalize_csv_row(raw_row)
        name = row.get("name")
        email = row.get("email")

        if not name or not email:
            errors.append(CsvImportRowError(row=index, reason="Missing required name or email"))
            continue
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append(CsvImportRowError(row=index, reason=f"Invalid email: {email}"))
            continue

        email_key = email.lower()
        if email_key in seen_emails:
            errors.append(CsvImportRowError(row=index, reason=f"Duplicate email in this file: {email}"))
            continue
        existing = db.query(Candidate).filter(Candidate.email.ilike(email)).first()
        if existing:
            errors.append(CsvImportRowError(row=index, reason=f"Candidate with this email already exists: {email}"))
            continue

        resume = row.get("resume")
        resume_path = resume if resume and resume.lower().startswith(("http://", "https://")) else None

        candidate = Candidate(
            full_name=name,
            email=email,
            phone=row.get("phone") or None,
            resume_path=resume_path,
            source="csv_import",
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)

        log_action(
            db, "candidate", candidate.id, "candidate_csv_imported", current_user.email, {"row": index, "email": email}
        )
        seen_emails.add(email_key)
        imported_ids.append(candidate.id)

    return CsvImportSummary(
        imported=len(imported_ids),
        skipped=len(errors),
        errors=errors,
        imported_candidate_ids=imported_ids,
    )


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return _get_candidate_or_404(db, candidate_id)


@router.get("/{candidate_id}/resume")
def download_resume(
    candidate_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    candidate = _get_candidate_or_404(db, candidate_id)
    if not candidate.resume_path:
        raise HTTPException(status_code=404, detail="No resume uploaded for this candidate")

    file_path = resolve_resume_path(candidate.resume_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file missing on disk")

    return FileResponse(path=file_path, filename=file_path.name)


@router.post("/{candidate_id}/parse-resume", response_model=CandidateRead)
def parse_candidate_resume(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    candidate = _get_candidate_or_404(db, candidate_id)
    try:
        parse_and_apply_resume(db, candidate)
    except NoResumeUploadedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResumeFileMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc
    except ResumeParsingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return candidate
