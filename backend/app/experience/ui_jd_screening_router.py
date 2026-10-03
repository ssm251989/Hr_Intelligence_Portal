"""Part 19.1: Screening without the Jobs module -- score candidates against a job description
pasted (or uploaded) on the Screening page. No job record is needed: candidates from the talent
pool are matched with the same AI matcher screening uses (ai_services.resume_matcher).

- POST /api/v1/ui/screening/jd/text      a .pdf/.docx/.doc/.txt job description -> its text
- POST /api/v1/ui/screening/jd           {title, jd_text, candidate_ids?} -> scores (at most 25
                                         candidates per run; default = the newest parsed ones)
- GET  /api/v1/ui/screening/jd           earlier runs
- GET  /api/v1/ui/screening/jd/{id}      one run, best match first

Belongs to the Screening module (module_registry: ^/api/v1/ui/screening).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.jd_screening import JdScreening, JdScreeningResult
from app.models.user import User
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/screening/jd", tags=["ui-screening-jd"])
MAX_PER_RUN = 25
_MAX_FILE = 5 * 1024 * 1024


@router.post("/text")
async def jd_text_from_file(file: UploadFile = File(...), current_user: User = Depends(require_roles("recruiter", "admin"))):
    from app.candidates.resume_extraction import extract_text

    data = await file.read()
    if len(data) > _MAX_FILE:
        raise HTTPException(status_code=400, detail="The file is too big (5 MB at most).")
    name = file.filename or "jd.txt"
    if name.lower().endswith(".txt"):
        return {"text": data.decode("utf-8", errors="replace").strip()}
    try:
        text = extract_text(data, name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Couldn't read this file: {exc}. Paste the text instead.")
    return {"text": (text or "").strip()}


class RunIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    jd_text: str = Field(min_length=30, max_length=30000)
    candidate_ids: Optional[list[UUID]] = Field(default=None, max_length=MAX_PER_RUN)


def _result_row(r: JdScreeningResult, c: Optional[Candidate]) -> dict:
    return {"candidate_id": str(r.candidate_id), "name": (c.full_name if c else None) or (c.email if c else None) or "Candidate",
            "email": c.email if c else None, "location": c.location if c else None, "match_score": r.match_score,
            "recommendation": r.recommendation, "error": r.error}


def _run_out(db: Session, run: JdScreening) -> dict:
    rows = (db.query(JdScreeningResult, Candidate).outerjoin(Candidate, Candidate.id == JdScreeningResult.candidate_id)
            .filter(JdScreeningResult.screening_id == run.id).all())
    results = sorted((_result_row(r, c) for r, c in rows), key=lambda x: (x["match_score"] is None, -(x["match_score"] or 0)))
    return {"id": str(run.id), "title": run.title, "jd_text": run.jd_text, "created_by": run.created_by,
            "created_at": run.created_at.isoformat() if run.created_at else None, "results": results}


@router.post("")
def run_screening(body: RunIn, db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    from app.ai_services.resume_matcher import ResumeMatchError, match_resume

    tenant = require_current_tenant()
    q = db.query(Candidate).filter(Candidate.deleted_at.is_(None), Candidate.parsed_fields.isnot(None))
    if body.candidate_ids:
        q = q.filter(Candidate.id.in_(body.candidate_ids))
    candidates = q.order_by(Candidate.created_at.desc()).limit(MAX_PER_RUN).all()
    if not candidates:
        raise HTTPException(status_code=400, detail="No candidates with a read resume yet. Upload resumes on the Candidates page first.")
    run = JdScreening(tenant_id=tenant.tenant_id, title=body.title.strip(), jd_text=body.jd_text.strip(), created_by=current_user.email)
    db.add(run)
    db.flush()
    for c in candidates:
        result = JdScreeningResult(tenant_id=tenant.tenant_id, screening_id=run.id, candidate_id=c.id)
        try:
            out = match_resume(run.jd_text, c.parsed_fields or {}, candidate_location=c.location)
            result.match_score, result.recommendation, result.result_json = int(out.get("match_score") or 0), out.get("recommendation"), out
        except ResumeMatchError as exc:
            result.error = str(exc)[:500]
        db.add(result)
    db.commit()
    log_action(db, "jd_screening", run.id, "jd_screening_run", current_user.email[:50], {"title": run.title, "candidates": len(candidates)})
    return _run_out(db, run)


@router.get("")
def list_runs(db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    counts = dict(db.query(JdScreeningResult.screening_id, func.count(JdScreeningResult.id)).group_by(JdScreeningResult.screening_id).all())
    runs = db.query(JdScreening).order_by(JdScreening.created_at.desc()).limit(50).all()
    return [{"id": str(r.id), "title": r.title, "created_by": r.created_by, "created_at": r.created_at.isoformat() if r.created_at else None,
             "candidates": counts.get(r.id, 0)} for r in runs]


@router.get("/{run_id}")
def get_run(run_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    run = db.get(JdScreening, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="We couldn't find this screening.")
    return _run_out(db, run)
