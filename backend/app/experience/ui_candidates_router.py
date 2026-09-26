"""Part 15.4 (Candidates restyle): read-only helpers for the candidate profile screen.

GET /api/v1/ui/candidates/applications/{application_id}/evidence
    "Why this score" evidence lines (spec L-S2): for each skill the job asks for that the
    candidate's parsed resume also lists, the first line of the candidate's OWN resume text
    that mentions it, quoted verbatim (trimmed). Nothing here is AI-generated or invented --
    a skill with no literal mention in the resume text simply has no quote. Also returns the
    job's must-have skills the screening step recorded as missing, so the card can say
    "Missing: ..." beside the quotes.

Read-only: never writes to the database or the audit log. Same auth dependency and
tenant scoping (TenantOwned models through the request session) as the neighbouring
candidates/applications routers.
"""

import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError, extract_text
from app.candidates.storage import resolve_resume_path
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User

router = APIRouter(prefix="/api/v1/ui/candidates", tags=["ui-candidates"])

MAX_QUOTES = 5
MAX_QUOTE_CHARS = 180


class EvidenceLine(BaseModel):
    skill: str
    quote: str


class EvidenceResponse(BaseModel):
    application_id: uuid.UUID
    # False when there is no readable resume file (external link, missing file, unreadable).
    resume_readable: bool
    evidence: list[EvidenceLine]
    missing_skills: list[str]
    job_skills: list[str]


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def _resume_lines(candidate: Candidate) -> Optional[list[str]]:
    path_value = candidate.resume_path or ""
    if not path_value or path_value.startswith(("http://", "https://")):
        return None
    file_path = resolve_resume_path(path_value)
    if not file_path.exists():
        return None
    try:
        text = extract_text(file_path.read_bytes(), file_path.name)
    except (UnsupportedFileTypeError, ResumeExtractionError):
        return None
    lines = [re.sub(r"\s+", " ", line).strip(" \t-•*·") for line in text.splitlines()]
    return [line for line in lines if len(line) >= 12]


def _trim(line: str, start: int) -> str:
    if len(line) <= MAX_QUOTE_CHARS:
        return line
    begin = max(0, start - MAX_QUOTE_CHARS // 3)
    snippet = line[begin : begin + MAX_QUOTE_CHARS].strip()
    return ("…" if begin > 0 else "") + snippet + ("…" if begin + MAX_QUOTE_CHARS < len(line) else "")


@router.get("/applications/{application_id}/evidence", response_model=EvidenceResponse)
def application_evidence(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Application not found")

    job_skills: list[str] = []
    for skill in _as_list(job.technical_skills_must_have) + _as_list(job.technical_skills_good_to_have):
        if skill.lower() not in {s.lower() for s in job_skills}:
            job_skills.append(skill)

    missing = _as_list(application.missing_skills)
    missing_lower = {s.lower() for s in missing}
    parsed_skills = {s.lower() for s in _as_list((candidate.parsed_fields or {}).get("skills"))}

    lines = _resume_lines(candidate)
    evidence: list[EvidenceLine] = []
    used_lines: set[int] = set()
    if lines:
        # Job skills first (that is what the score is about), then the candidate's own skills.
        wanted = [s for s in job_skills if s.lower() not in missing_lower] or sorted(parsed_skills)
        for skill in wanted:
            if len(evidence) >= MAX_QUOTES:
                break
            pattern = re.compile(r"(?<![\w+#.])" + re.escape(skill) + r"(?![\w+#])", re.IGNORECASE)
            for index, line in enumerate(lines):
                if index in used_lines:
                    continue
                match = pattern.search(line)
                if match:
                    used_lines.add(index)
                    evidence.append(EvidenceLine(skill=skill, quote=_trim(line, match.start())))
                    break

    return EvidenceResponse(
        application_id=application.id,
        resume_readable=lines is not None,
        evidence=evidence,
        missing_skills=missing,
        job_skills=job_skills,
    )
