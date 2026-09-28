import uuid
from datetime import date, datetime, time, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import Float, cast, or_
from sqlalchemy.orm import Session, aliased

from app.ai_services.resume_parser import ResumeParsingError, parse_resume
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.gender_inference import infer_gender
from app.candidates.photo_extraction import extract_photo
from app.candidates.resume_extraction import (
    ResumeExtractionError,
    UnsupportedFileTypeError,
    extract_text,
)
from app.candidates.storage import resolve_photo_path, resolve_resume_path, save_photo_file, save_resume_file
from app.core.database import get_db
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.candidate import CandidateRead, CandidateUpdate
from app.schemas.candidates_dashboard import CandidateApplicationRow, CandidatesListPage
from app.screening.service import (
    SCREENING_REMARKS_ACTIONS,
    attempt_auto_screen,
    describe_interview_readiness,
    describe_screening_audit_entry,
)
from app.screening.suitability import attempt_auto_suggest_suitable_job

router = APIRouter(prefix="/candidates", tags=["candidates"])

ALLOWED_EXTENSIONS = {"pdf", "docx"}
# "manual" is the existing single-candidate "Upload Resume" flow; "local_import" is the
# Import wizard's "Import from Local" step (bulk-selecting several files at once) --
# looping over this same endpoint once per file client-side, same as a single upload,
# just tagged with the source it actually came through. Nothing else may pass its own
# source here (e.g. spoofing "career_portal").
UPLOAD_SOURCES = {"manual", "local_import"}
# Part 18.9: resumes downloaded from a job board are uploaded with that board as the source
UPLOAD_SOURCES |= {"linkedin", "naukri", "indeed", "monster", "shine"}

# Aliased so a query can join job_roles twice -- once for the application's actual job
# (JobRole), once for the candidate's suggested "Suitable For" job (SuitableJob).
SuitableJob = aliased(JobRole)

# Aliased so a query can join audit_log once for "whichever screening entry is latest for
# this application" -- see _latest_screening_audit_id below.
ScreeningAuditEntry = aliased(AuditLog)


def _latest_screening_audit_id(db: Session):
    """A correlated scalar subquery -- for each Application row in the outer query, the id
    of its own most recent ai_screening_scored/ai_screening_failed audit_log entry (or NULL
    if it's never been screened). Joining AuditLog on this id (see ScreeningAuditEntry
    below) gets every row its Remarks text in one query, rather than one extra query per
    row -- the export endpoint in particular can return every application system-wide in a
    single call, so an N+1 lookup here would scale badly.
    """
    return (
        db.query(AuditLog.id)
        .filter(
            AuditLog.entity_type == "application",
            AuditLog.entity_id == Application.id,
            AuditLog.action.in_(SCREENING_REMARKS_ACTIONS),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )


class NoResumeUploadedError(Exception):
    """Raised when a candidate has no resume_path to parse."""


class ResumeFileMissingError(Exception):
    """Raised when a candidate's resume_path doesn't resolve to a file on disk."""


def _get_candidate_or_404(db: Session, candidate_id: uuid.UUID) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _with_inferred_gender(candidate: Candidate) -> Candidate:
    # Not a real column -- a plain instance attribute set just before serialization, same
    # pattern as JobRole's computed application_count/avg_time_to_hire_days (see
    # app/jobs/router.py _attach_table_stats). CandidateRead.from_attributes reads it like
    # any other field.
    candidate.inferred_gender = infer_gender(candidate.full_name)
    return candidate


def parse_and_apply_resume(
    db: Session, candidate: Candidate, precomputed_result: Optional[dict] = None, actor: str = "system"
) -> dict:
    """Extract text from a candidate's uploaded resume, AI-parse it, and apply the
    result onto the candidate record. Shared by the authenticated parse-resume endpoint,
    the public careers portal's background parsing after a direct application, and Part G's
    local-import scan (which passes precomputed_result -- its own resumes are already parsed
    via a Batch API call before this runs, so there's nothing left to extract/parse here,
    only the apply-to-candidate/screen/suggest steps below, identical either way).
    """
    if not candidate.resume_path:
        raise NoResumeUploadedError("No resume uploaded for this candidate")

    file_path = resolve_resume_path(candidate.resume_path)
    if not file_path.exists():
        raise ResumeFileMissingError("Resume file missing on disk")

    if precomputed_result is not None:
        result = precomputed_result
    else:
        raw_text = extract_text(file_path.read_bytes(), file_path.name)
        from app.platform.ai.tracked import ai_subject  # Part 18.24: cost per candidate

        with ai_subject("candidate", candidate.id):
            result = parse_resume(raw_text)

    log_action(db, "candidate", candidate.id, "ai_resume_parser_scored", actor, result)
    candidate.parsed_fields = result
    candidate.full_name = result.get("full_name") or candidate.full_name
    candidate.email = result.get("email") or candidate.email
    candidate.phone = result.get("phone") or candidate.phone
    candidate.location = result.get("location") or candidate.location
    if result.get("languages") and not candidate.languages:
        candidate.languages = result.get("languages")

    # Best-effort candidate photo -- never allowed to fail or block the parse above it. No
    # embedded image found (or any error extracting/saving one) just leaves photo_path as
    # it already was, rather than surfacing anywhere but here.
    try:
        photo = extract_photo(file_path.read_bytes(), file_path.name)
        if photo:
            image_bytes, extension = photo
            candidate.photo_path = save_photo_file(image_bytes, extension)
    except Exception:
        pass

    db.commit()
    db.refresh(candidate)

    # Part 17.8: salary figures stated in the resume fill only what's still empty.
    try:
        from app.platform.tenancy.context import require_current_tenant
        from app.recruitment.salary_auto import take_figures

        take_figures(db, require_current_tenant(), candidate, {k: result.get(k) for k in ("current_ctc", "expected_ctc", "notice_period_days")}, source="resume")
    except Exception:  # noqa: BLE001 -- never blocks parsing
        pass

    # Automatic screening (Part A): covers the career-portal path (application created
    # before the resume is parsed in the background) and a manual re-parse of a candidate
    # who already has a 'received' application -- both only become screenable once parsing
    # completes, which just happened. The manual-upload path instead becomes screenable when
    # a job gets linked afterward (see applications_router.py create_application's own call
    # to this same best-effort helper); Part G's local-import creates that same link itself,
    # right after this function returns (see app/local_import/service.py).
    for application in db.query(Application).filter(Application.candidate_id == candidate.id).all():
        attempt_auto_screen(db, application, actor)

    # Suitable-For suggestion (Part B): informational only -- picks the best-fitting
    # published job for this candidate, entirely independent of (and without ever
    # touching) whichever job(s) they actually applied for above. Part G reads
    # candidate.suitable_job_id straight back off `candidate` after this call returns.
    attempt_auto_suggest_suitable_job(db, candidate, actor)

    return result


@router.post("/upload", response_model=CandidateRead, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    source: str = Form("manual"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    if source not in UPLOAD_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {sorted(UPLOAD_SOURCES)}")

    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")

    file_bytes = await file.read()

    try:
        extract_text(file_bytes, file.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc

    resume_path = save_resume_file(file_bytes, extension)

    from app.recruitment.automation import file_hash, find_duplicate

    candidate = Candidate(resume_path=resume_path, source=source, resume_sha256=file_hash(file_bytes))
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    # Part 17.13: the same resume file uploaded before -> linked as a possible duplicate
    from app.platform.tenancy.context import require_current_tenant as _rct

    other, reason = find_duplicate(db, _rct(), resume_sha256=candidate.resume_sha256, exclude_id=candidate.id)
    if other is not None:
        candidate.duplicate_of_id = other.id
        db.commit()
        log_action(db, "candidate", candidate.id, "possible_duplicate", current_user.email[:50], {"of": str(other.id), "reason": reason})

    log_action(db, "candidate", candidate.id, "candidate_uploaded", "system", {"resume_path": resume_path})
    return _with_inferred_gender(candidate)


@router.get("", response_model=list[CandidateRead])
def list_candidates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).all()
    return [_with_inferred_gender(c) for c in candidates]


def row_to_item(
    application: Application,
    candidate: Candidate,
    job_title: str,
    suitable_job_title: Optional[str] = None,
    screening_action: Optional[str] = None,
    screening_details: Optional[dict] = None,
) -> CandidateApplicationRow:
    """Shared by GET /candidates/applications (Candidates List page) and the reports
    dashboard's recent_candidates (Recent Candidates table) -- previously duplicated as
    two independently-maintained copies (this one, and reports/router.py's
    _candidate_application_row), which is exactly how the dashboard's copy silently never
    picked up photo_path/inferred_gender when those fields were added here. One function,
    imported by reports/router.py, so that can't happen again.

    suitable_job_title/screening_action/screening_details are looked up by the caller's own
    query (joins on SuitableJob / ScreeningAuditEntry above) rather than here, since this
    function has no db session of its own -- see _filtered_candidate_applications_query and
    reports/router.py's recent_rows query."""
    experience_years = None
    if candidate.parsed_fields:
        experience_years = candidate.parsed_fields.get("total_experience_years")
    # Remarks (Part C) and Interview Readiness Remarks (Part F): two different renderings
    # of that SAME latest screening audit_log entry -- never separately maintained strings,
    # and never a second query/join (screening_action/screening_details already is "whichever
    # entry is latest," looked up once by the caller).
    remarks = describe_screening_audit_entry(screening_action, screening_details or {}) if screening_action else None
    interview_remarks = (
        describe_interview_readiness(screening_action, screening_details or {}) if screening_action else None
    )
    return CandidateApplicationRow(
        application_id=application.id,
        candidate_id=candidate.id,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        job_role_id=application.job_role_id,
        job_title=job_title,
        status=application.status,
        hold_reason=getattr(application, 'hold_reason', None),
        tags=list(candidate.tags or []),
        notice_period_days=candidate.notice_period_days,
        source=candidate.source,
        location=candidate.location,
        applied_on=application.created_at,
        match_score=float(application.match_score) if application.match_score is not None else None,
        composite_score=float(application.composite_score) if application.composite_score is not None else None,
        skill_match_pct=float(application.skill_match_pct) if application.skill_match_pct is not None else None,
        ranking_score=float(application.ranking_score) if application.ranking_score is not None else None,
        experience_years=float(experience_years) if experience_years is not None else None,
        resume_path=candidate.resume_path,
        photo_path=candidate.photo_path,
        inferred_gender=infer_gender(candidate.full_name),
        suitable_job_id=candidate.suitable_job_id,
        suitable_job_title=suitable_job_title,
        suitable_job_score=float(candidate.suitable_job_score) if candidate.suitable_job_score is not None else None,
        remarks=remarks,
        interview_remarks=interview_remarks,
        knocked_out=bool(getattr(application, "knocked_out", False)),
        knockout_reasons=_knockout_reasons(screening_action, screening_details),
    )


def _knockout_reasons(screening_action: Optional[str], screening_details: Optional[dict]) -> list[str]:
    """Part 17.6: the plain reasons of the failed knock-outs on the latest scoring entry."""
    if screening_action != "ai_screening_scored" or not screening_details:
        return []
    out = []
    for k in screening_details.get("knockouts") or []:
        if isinstance(k, dict) and not k.get("passed"):
            text = k.get("reason") or k.get("label")
            if text:
                out.append(str(text))
    return out


def _filtered_candidate_applications_query(
    db: Session,
    *,
    job_role_id: Optional[uuid.UUID],
    status: Optional[str],
    source: Optional[str],
    location: Optional[str],
    search: Optional[str],
    experience_min: Optional[float],
    experience_max: Optional[float],
    applied_after: Optional[date],
    applied_before: Optional[date],
    match_score_min: Optional[float],
    match_score_max: Optional[float],
    score_field: Literal["match_score", "composite_score"] = "match_score",
    notice_max: Optional[int] = None,
    tags: Optional[str] = None,
):
    """Shared by the paginated List page endpoint and the unpaginated export endpoint --
    one filter-building implementation so the two can never quietly drift apart (e.g. an
    export that "matches the current filters" except for one filter someone forgot to
    port over to a second copy of this logic).

    Also shared by the Candidates List and Screening List pages, which reuse this same
    endpoint with the same match_score_min/max values but a different score_field: the
    Candidates List's "Match Score" filter always targets the raw Resume Matcher score
    (score_field left at its default), while the Screening List's "Screening Score" filter
    targets composite_score instead -- the same column that page's primary score column
    actually shows (see frontend utils/screeningScore.ts). One filter UI, one pair of
    min/max values, just aimed at whichever column that page's own score column is."""
    query = (
        db.query(
            Application, Candidate, JobRole.title, SuitableJob.title,
            ScreeningAuditEntry.action, ScreeningAuditEntry.details,
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .outerjoin(SuitableJob, SuitableJob.id == Candidate.suitable_job_id)
        .outerjoin(ScreeningAuditEntry, ScreeningAuditEntry.id == _latest_screening_audit_id(db))
    )
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    if status is not None:
        # Part 17.2: "a,b,c" = any of these (the Home funnel links one stage = several statuses).
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        query = query.filter(Application.status.in_(statuses) if len(statuses) > 1 else Application.status == status.strip())
    if source is not None:
        query = query.filter(Candidate.source == source)
    if location is not None:
        query = query.filter(Candidate.location.ilike(f"%{location}%"))
    if search is not None:
        query = query.filter(
            or_(Candidate.full_name.ilike(f"%{search}%"), Candidate.email.ilike(f"%{search}%"))
        )
    # Parsed experience lives in candidate.parsed_fields (JSONB), not a real column --
    # candidates with no parsed_fields or no total_experience_years key just never match a
    # min/max filter here (NULL comparisons are never true), same as leaving them out.
    experience_expr = cast(Candidate.parsed_fields["total_experience_years"].astext, Float)
    if experience_min is not None:
        query = query.filter(experience_expr >= experience_min)
    if experience_max is not None:
        query = query.filter(experience_expr <= experience_max)
    if applied_after is not None:
        query = query.filter(Application.created_at >= datetime.combine(applied_after, time.min, tzinfo=timezone.utc))
    if applied_before is not None:
        query = query.filter(Application.created_at <= datetime.combine(applied_before, time.max, tzinfo=timezone.utc))
    score_column = Application.composite_score if score_field == "composite_score" else Application.match_score
    if match_score_min is not None:
        query = query.filter(score_column >= match_score_min)
    if match_score_max is not None:
        query = query.filter(score_column <= match_score_max)
    # Part 18.10: notice period (days) and tags (any of the given ones)
    if notice_max is not None:
        query = query.filter(Candidate.notice_period_days <= notice_max)
    wanted = [t.strip().lower() for t in (tags or "").split(",") if t.strip()]
    if wanted:
        query = query.filter(Candidate.tags.overlap(wanted))
    return query


# NOTE: registered before the "/{candidate_id}" routes below -- FastAPI/Starlette match
# routes in registration order using the default string convertor for un-annotated path
# segments, so a literal path like "/applications" registered *after* "/{candidate_id}"
# would be swallowed by that param route first (and 422 trying to parse "applications"
# as a UUID) rather than ever reaching this handler.
@router.get("/applications", response_model=CandidatesListPage)
def list_candidate_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    search: Optional[str] = Query(None, description="Matches candidate name or email"),
    job_role_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    experience_min: Optional[float] = Query(None, description="Minimum parsed total years of experience"),
    experience_max: Optional[float] = Query(None, description="Maximum parsed total years of experience"),
    applied_after: Optional[date] = Query(None, description="Applications created on/after this date"),
    applied_before: Optional[date] = Query(None, description="Applications created on/before this date"),
    match_score_min: Optional[float] = Query(None, ge=0, le=100),
    match_score_max: Optional[float] = Query(None, ge=0, le=100),
    notice_max: Optional[int] = Query(None, ge=0, le=365, description="Part 18.10: notice period at most this many days"),
    tags: Optional[str] = Query(None, description="Part 18.10: comma-separated tags (any of them)"),
    score_field: Literal["match_score", "composite_score"] = Query(
        "match_score",
        description="Which column match_score_min/max filter -- the raw Resume Matcher "
        "score (Candidates List's 'Match Score' filter) or Part A's composite_score "
        "(Screening List's 'Screening Score' filter).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per (candidate, application) pairing -- the data source for both the
    Candidates List page and the Screening List page. A candidate who applied to multiple
    jobs appears once per job, since Job Applied/Stage/Match Score are all per-application
    concepts.

    page_size is capped at 200 -- this endpoint is for rendering one page of the table, not
    for bulk export (see GET /applications/export below, which is unpaginated on purpose)."""
    query = _filtered_candidate_applications_query(
        db,
        job_role_id=job_role_id,
        status=status,
        source=source,
        location=location,
        search=search,
        experience_min=experience_min,
        experience_max=experience_max,
        applied_after=applied_after,
        applied_before=applied_before,
        match_score_min=match_score_min,
        match_score_max=match_score_max, notice_max=notice_max, tags=tags,
        score_field=score_field,
    )

    total = query.count()
    rows = (
        query.order_by(Application.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        row_to_item(application, candidate, title, suitable_title, screening_action, screening_details)
        for application, candidate, title, suitable_title, screening_action, screening_details in rows
    ]
    return CandidatesListPage(total=total, page=page, page_size=page_size, items=items)


@router.get("/applications/export", response_model=list[CandidateApplicationRow])
def export_candidate_applications(
    application_ids: Optional[list[uuid.UUID]] = Query(
        None, description="Export exactly these applications (row selection), ignoring every filter below"
    ),
    search: Optional[str] = Query(None),
    job_role_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    experience_min: Optional[float] = Query(None),
    experience_max: Optional[float] = Query(None),
    applied_after: Optional[date] = Query(None),
    applied_before: Optional[date] = Query(None),
    match_score_min: Optional[float] = Query(None, ge=0, le=100),
    match_score_max: Optional[float] = Query(None, ge=0, le=100),
    notice_max: Optional[int] = Query(None, ge=0, le=365, description="Part 18.10: notice period at most this many days"),
    tags: Optional[str] = Query(None, description="Part 18.10: comma-separated tags (any of them)"),
    score_field: Literal["match_score", "composite_score"] = Query("match_score"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unpaginated -- returns every matching row (or, if application_ids is given, exactly
    those rows and nothing else), for the List page's CSV export button. Deliberately a
    separate endpoint from GET /applications above rather than that endpoint with a raised
    page_size cap: the List page always needs a bounded, fast single page for rendering,
    while export always needs the complete result set regardless of size -- two different
    contracts that don't belong on one query-param-tunable endpoint."""
    if application_ids:
        query = (
            db.query(
                Application, Candidate, JobRole.title, SuitableJob.title,
                ScreeningAuditEntry.action, ScreeningAuditEntry.details,
            )
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(JobRole, JobRole.id == Application.job_role_id)
            .outerjoin(SuitableJob, SuitableJob.id == Candidate.suitable_job_id)
            .outerjoin(ScreeningAuditEntry, ScreeningAuditEntry.id == _latest_screening_audit_id(db))
            .filter(Application.id.in_(application_ids))
        )
    else:
        query = _filtered_candidate_applications_query(
            db,
            job_role_id=job_role_id,
            status=status,
            source=source,
            location=location,
            search=search,
            experience_min=experience_min,
            experience_max=experience_max,
            applied_after=applied_after,
            applied_before=applied_before,
            match_score_min=match_score_min,
            match_score_max=match_score_max, notice_max=notice_max, tags=tags,
            score_field=score_field,
        )

    rows = query.order_by(Application.created_at.desc()).all()
    return [
        row_to_item(application, candidate, title, suitable_title, screening_action, screening_details)
        for application, candidate, title, suitable_title, screening_action, screening_details in rows
    ]


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return _with_inferred_gender(_get_candidate_or_404(db, candidate_id))


@router.patch("/{candidate_id}", response_model=CandidateRead)
def update_candidate(
    candidate_id: uuid.UUID,
    payload: CandidateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    candidate = _get_candidate_or_404(db, candidate_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(candidate, field, value)
    db.commit()
    db.refresh(candidate)
    log_action(db, "candidate", candidate.id, "candidate_contact_info_updated", current_user.email, updates)
    return _with_inferred_gender(candidate)


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


@router.get("/{candidate_id}/photo")
def download_photo(
    candidate_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    candidate = _get_candidate_or_404(db, candidate_id)
    if not candidate.photo_path:
        raise HTTPException(status_code=404, detail="No photo available for this candidate")

    file_path = resolve_photo_path(candidate.photo_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Photo file missing on disk")

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
    return _with_inferred_gender(candidate)
