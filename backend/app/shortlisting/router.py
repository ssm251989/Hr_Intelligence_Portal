import uuid
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.ai_services.shortlist_feedback_generator import (
    ShortlistFeedbackGenerationError,
    generate_shortlist_feedback,
)
from app.candidates.hold import assert_application_not_on_hold
from app.candidates.router import (
    ScreeningAuditEntry,
    SuitableJob,
    _filtered_candidate_applications_query,
    _latest_screening_audit_id,
    row_to_item,
)
from app.core.database import get_db
from app.interview_scheduling.negotiation import clear_manual_scheduling_flag
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.application import ApplicationRead, ShortlistDecisionRequest
from app.schemas.candidates_dashboard import CandidateApplicationRow, CandidatesListPage
from app.schemas.shortlisting import (
    ShortlistBulkDecisionRequest,
    ShortlistBulkDecisionResult,
    ShortlistBulkDecisionSkipped,
    ShortlistFeedbackSuggestionResponse,
    ShortlistStatusUpdateRequest,
)
from app.shortlisting.service import (
    SHORTLIST_STATUSES,
    SHORTLISTED,
    shortlisting_scope_condition,
    update_shortlist_status,
)

def _start_scheduling(db, application, user) -> None:
    """Fix 2026-10-04: a manual shortlist starts scheduling exactly like an automatic one
    (scheduling mode, problems shown + recruiter told, mailbox failures retried)."""
    from app.interview_scheduling import automation
    from app.platform.tenancy.context import require_current_tenant

    automation.start(db, require_current_tenant(), application, user, trigger="manual_shortlist")


router = APIRouter(tags=["shortlisting"])

_ShortlistStatusFilter = Literal["under_review", "shortlisted", "on_hold", "not_shortlisted"]


@router.get("/jobs/{job_id}/shortlist", response_model=list[ApplicationRead])
def list_shortlist(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Application)
        .filter(Application.job_role_id == job_id, Application.status == "screened")
        .order_by(Application.match_score.desc())
        .all()
    )


@router.post("/applications/{application_id}/shortlist-decision", response_model=ApplicationRead)
def make_shortlist_decision(
    application_id: uuid.UUID,
    payload: ShortlistDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_not_on_hold(application)
    if application.status != "screened":
        raise HTTPException(
            status_code=400,
            detail="Application must be screened before a shortlisting decision can be made",
        )

    previous_status = application.status
    new_status = "hr_selected" if payload.decision == "select" else "hr_rejected"
    application.status = new_status
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "hr_shortlisting_decision",
        payload.decided_by or current_user.email,
        {
            "decision": payload.decision,
            "notes": payload.notes,
            "previous_status": previous_status,
            "new_status": new_status,
            "match_score": float(application.match_score) if application.match_score is not None else None,
        },
    )
    if new_status == "hr_selected":
        clear_manual_scheduling_flag(db, application, current_user.email)
        _start_scheduling(db, application, current_user)
        from app.shortlisting.service import _salary_after_shortlist

        _salary_after_shortlist(db, application, current_user.email)
    return application


def _apply_shortlist_status_filter(query, shortlist_status: Optional[str]):
    """Narrows an already-filtered candidate-applications query to one of the 4 named
    shortlist states, or (when none is given) to every application in the shortlisting
    stage's own scope -- see app.shortlisting.service.shortlisting_scope_condition."""
    if shortlist_status is None:
        return query.filter(shortlisting_scope_condition())
    if shortlist_status == "under_review":
        return query.filter(Application.status == "screened")
    if shortlist_status == "shortlisted":
        return query.filter(Application.status == "hr_selected")
    if shortlist_status == "not_shortlisted":
        return query.filter(Application.status == "hr_rejected")
    if shortlist_status == "on_hold":
        return query.filter(Application.status == "on_hold", Application.previous_status == "screened")
    raise HTTPException(status_code=400, detail=f"shortlist_status must be one of {SHORTLIST_STATUSES}")


@router.get("/shortlisting/list", response_model=CandidatesListPage)
def list_shortlisting(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    search: Optional[str] = Query(None, description="Matches candidate name or email"),
    job_role_id: Optional[uuid.UUID] = Query(None),
    shortlist_status: Optional[_ShortlistStatusFilter] = Query(None),
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The Shortlisting List (redesign, matching the Candidates/Screening Lists'
    architecture) -- unlike those two, which show every application system-wide, this one is
    scoped to applications actually in the shortlisting stage (see app.shortlisting.service.
    shortlisting_scope_condition): screened, hr_selected, hr_rejected, or on_hold-from-
    screened. match_score_min/max targets composite_score, same as the Screening List's
    "Screening %" filter -- the same column this page's own Screening Score column shows."""
    query = _filtered_candidate_applications_query(
        db,
        job_role_id=job_role_id,
        status=None,
        source=source,
        location=location,
        search=search,
        experience_min=experience_min,
        experience_max=experience_max,
        applied_after=applied_after,
        applied_before=applied_before,
        match_score_min=match_score_min,
        match_score_max=match_score_max, notice_max=notice_max, tags=tags,
        score_field="composite_score",
    )
    query = _apply_shortlist_status_filter(query, shortlist_status)

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


@router.get("/shortlisting/export", response_model=list[CandidateApplicationRow])
def export_shortlisting(
    application_ids: Optional[list[uuid.UUID]] = Query(
        None, description="Export exactly these applications (row selection), ignoring every filter below"
    ),
    search: Optional[str] = Query(None),
    job_role_id: Optional[uuid.UUID] = Query(None),
    shortlist_status: Optional[_ShortlistStatusFilter] = Query(None),
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unpaginated CSV-export counterpart to GET /shortlisting/list -- same scoping/filter
    rules, same row shape, same application_ids row-selection override as /applications/
    export."""
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
            status=None,
            source=source,
            location=location,
            search=search,
            experience_min=experience_min,
            experience_max=experience_max,
            applied_after=applied_after,
            applied_before=applied_before,
            match_score_min=match_score_min,
            match_score_max=match_score_max, notice_max=notice_max, tags=tags,
            score_field="composite_score",
        )
        query = _apply_shortlist_status_filter(query, shortlist_status)

    rows = query.order_by(Application.created_at.desc()).all()
    return [
        row_to_item(application, candidate, title, suitable_title, screening_action, screening_details)
        for application, candidate, title, suitable_title, screening_action, screening_details in rows
    ]


@router.post("/applications/{application_id}/shortlist-status", response_model=ApplicationRead)
def update_shortlist_status_endpoint(
    application_id: uuid.UUID,
    payload: ShortlistStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """The Update Shortlist Status panel's Save action -- enforces the 4-state transition
    rules in app.shortlisting.service.update_shortlist_status. reason/feedback are optional
    (a plain Under Review -> On Hold pause needs neither), both logged verbatim onto the
    same shortlist_status_updated audit_log entry the Shortlisting Timeline reads."""
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    updated = update_shortlist_status(
        db, application, payload.target_status, current_user.email, reason=payload.reason, feedback=payload.feedback
    )
    if payload.target_status == SHORTLISTED:
        clear_manual_scheduling_flag(db, updated, current_user.email)
        _start_scheduling(db, updated, current_user)
    return updated


@router.post("/shortlisting/bulk-decision", response_model=ShortlistBulkDecisionResult)
def bulk_shortlist_decision(
    payload: ShortlistBulkDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """The Shortlisting List's bulk-select "Shortlist Selected"/"Reject Selected" actions --
    still a fully human-triggered decision for every row (the recruiter selected each one
    and confirmed the batch in a dialog listing them by name); this endpoint is a UI
    convenience for applying the SAME per-application transition validation as POST
    .../shortlist-status to many applications in one call, not a bypass of it.

    Every application ID is attempted independently -- one already-decided or otherwise
    invalid row is skipped (with its real rejection reason) rather than failing the whole
    batch, so a partial success is always possible and always reported."""
    succeeded: list[uuid.UUID] = []
    skipped: list[ShortlistBulkDecisionSkipped] = []
    for application_id in payload.application_ids:
        application = db.get(Application, application_id)
        if not application:
            skipped.append(ShortlistBulkDecisionSkipped(application_id=application_id, reason="Application not found"))
            continue
        try:
            updated = update_shortlist_status(
                db, application, payload.target_status, current_user.email,
                reason=payload.reason, feedback=payload.feedback,
            )
        except HTTPException as exc:
            skipped.append(ShortlistBulkDecisionSkipped(application_id=application_id, reason=str(exc.detail)))
            continue
        if payload.target_status == SHORTLISTED:
            clear_manual_scheduling_flag(db, updated, current_user.email)
            _start_scheduling(db, updated, current_user)
        succeeded.append(application_id)
    return ShortlistBulkDecisionResult(succeeded=succeeded, skipped=skipped)


@router.post(
    "/applications/{application_id}/shortlist-feedback-suggestion",
    response_model=ShortlistFeedbackSuggestionResponse,
)
def suggest_shortlist_feedback(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """The Update Shortlist Status panel's "AI Suggestion" button -- one Haiku call over the
    candidate's real screening data (composite score, matched skills, missing skills),
    returning a draft paragraph. Advisory only: this endpoint never writes to the
    application itself, only to audit_log (for the same reason every other AI call in this
    app logs its raw output -- see docs/PROMPTS.md) -- the evaluator must explicitly Save via
    POST .../shortlist-status for anything to actually persist, and may edit the text
    freely first."""
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if not candidate or not job:
        raise HTTPException(status_code=400, detail="Candidate or job not found for this application")

    missing_skills = application.missing_skills or []
    candidate_skills = (candidate.parsed_fields or {}).get("skills") or []
    matched_skills = [skill for skill in candidate_skills if skill not in missing_skills]
    composite_score = float(application.composite_score) if application.composite_score is not None else None

    try:
        feedback = generate_shortlist_feedback(
            candidate_name=candidate.full_name or "This candidate",
            job_title=job.title,
            composite_score=composite_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
        )
    except ShortlistFeedbackGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_action(
        db,
        "application",
        application.id,
        "ai_shortlist_feedback_suggested",
        current_user.email,
        {
            "composite_score": composite_score,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "suggested_feedback": feedback,
        },
    )
    return ShortlistFeedbackSuggestionResponse(suggested_feedback=feedback)
