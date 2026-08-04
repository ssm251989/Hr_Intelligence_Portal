import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai_services.resume_parser import parse_resume
from app.audit.service import log_action
from app.candidates.resume_extraction import (
    ResumeExtractionError,
    UnsupportedFileTypeError,
    extract_text,
)
from app.candidates.storage import resolve_resume_path, save_resume_file
from app.core.database import get_db
from app.models.candidate import Candidate
from app.schemas.candidate import CandidateRead

router = APIRouter(prefix="/candidates", tags=["candidates"])

ALLOWED_EXTENSIONS = {"pdf", "docx"}


def _get_candidate_or_404(db: Session, candidate_id: uuid.UUID) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post("/upload", response_model=CandidateRead, status_code=201)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")

    file_bytes = await file.read()

    try:
        extract_text(file_bytes, file.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    resume_path = save_resume_file(file_bytes, extension)

    candidate = Candidate(resume_path=resume_path)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    log_action(db, "candidate", candidate.id, "candidate_uploaded", "system", {"resume_path": resume_path})
    return candidate


@router.get("", response_model=list[CandidateRead])
def list_candidates(db: Session = Depends(get_db)):
    return db.query(Candidate).order_by(Candidate.created_at.desc()).all()


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(candidate_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_candidate_or_404(db, candidate_id)


@router.get("/{candidate_id}/resume")
def download_resume(candidate_id: uuid.UUID, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    if not candidate.resume_path:
        raise HTTPException(status_code=404, detail="No resume uploaded for this candidate")

    file_path = resolve_resume_path(candidate.resume_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file missing on disk")

    return FileResponse(path=file_path, filename=file_path.name)


@router.post("/{candidate_id}/parse-resume", response_model=CandidateRead)
def parse_candidate_resume(candidate_id: uuid.UUID, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    if not candidate.resume_path:
        raise HTTPException(status_code=400, detail="No resume uploaded for this candidate")

    file_path = resolve_resume_path(candidate.resume_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file missing on disk")

    try:
        raw_text = extract_text(file_path.read_bytes(), file_path.name)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    result = parse_resume(raw_text)

    log_action(db, "candidate", candidate.id, "ai_resume_parser_scored", "system", result)
    candidate.parsed_fields = result
    db.commit()
    db.refresh(candidate)
    return candidate
