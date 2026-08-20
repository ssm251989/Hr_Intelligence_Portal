import uuid
from datetime import date, datetime, time, timezone
from typing import Literal, Optional

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai_services.interview_question_generator import (
    InterviewQuestionGenerationError,
    generate_interview_questions,
)
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.crypto import decrypt
from app.core.database import get_db
from app.integrations.google_calendar import GoogleCalendarError, create_calendar_event
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.reports import stats
from app.schemas.interview import (
    InterviewCreate,
    InterviewFeedbackUpdate,
    InterviewQuestionsResponse,
    InterviewRead,
)
from app.schemas.interviews_dashboard import INTERVIEW_STATUSES, InterviewListRow, InterviewsListPage

router = APIRouter(tags=["scheduling"])

SCHEDULABLE_STATUSES = {"hr_selected", "interview_scheduled"}


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _get_interview_or_404(db: Session, interview_id: uuid.UUID) -> Interview:
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def _try_create_calendar_event(
    db: Session, application: Application, interviewer: User, scheduled_at
) -> dict | None:
    """Create a real Google Calendar event if the interviewer has connected their account.

    Returns None (never raises) when there's no connection or the Google API call fails,
    so a calendar outage can't block scheduling -- callers fall back to the manual link.
    """
    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == interviewer.id, UserIntegration.provider == "google")
        .first()
    )
    if not integration:
        return None

    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    attendee_emails = [email for email in (candidate.email if candidate else None, interviewer.email) if email]

    try:
        return create_calendar_event(
            decrypt(integration.refresh_token),
            summary=f"Interview: {candidate.full_name if candidate else 'Candidate'} — {job.title if job else 'Role'}",
            description=f"Interview scheduled via HR Automation for application {application.id}.",
            start=scheduled_at,
            attendee_emails=attendee_emails,
        )
    except (GoogleCalendarError, InvalidToken) as exc:
        error = str(exc) or "Stored Google refresh token could not be decrypted"
        log_action(
            db,
            "interview",
            application.id,
            "calendar_event_creation_failed",
            "system",
            {"interviewer_id": str(interviewer.id), "error": error},
        )
        return None


def interview_row_to_item(
    interview: Interview,
    application: Application,
    candidate: Candidate,
    job_title: str,
    interviewer: Optional[User],
    computed_status: str,
) -> InterviewListRow:
    """Shared by GET /interviews (Interview List page) and the Interview Dashboard's
    Recent Interviews table -- same "one row builder, imported by reports/router.py"
    pattern as app/candidates/router.py's row_to_item. computed_status is passed in
    (rather than recomputed here) because it's selected straight off the query via
    app.reports.stats.interview_status_case, so the List page's status *filter* and this
    row's displayed status can never drift apart."""
    return InterviewListRow(
        interview_id=interview.id,
        application_id=application.id,
        candidate_id=candidate.id,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        job_role_id=application.job_role_id,
        job_title=job_title,
        interviewer_id=interview.interviewer_id,
        interviewer_name=(interviewer.full_name or interviewer.email) if interviewer else None,
        scheduled_at=interview.scheduled_at,
        scheduling_method=interview.scheduling_method,
        status=computed_status,
        decision=interview.decision,
        meeting_link=interview.meeting_link,
        calendar_link=interview.calendar_link,
        created_at=interview.created_at,
    )


def filtered_interviews_query(
    db: Session,
    *,
    job_role_id: Optional[uuid.UUID],
    interviewer_id: Optional[uuid.UUID],
    status: Optional[str],
    scheduling_method: Optional[str],
    scheduled_after: Optional[date],
    scheduled_before: Optional[date],
    now: Optional[datetime] = None,
):
    """Shared by the Interview List page (GET /interviews) and the Interview Dashboard's
    Recent Interviews table (app/reports/router.py get_interviews_dashboard_stats) -- one
    filter-building query so the two can't quietly define "which interviews" differently."""
    now = now or datetime.now(timezone.utc)
    status_expr = stats.interview_status_case(now)
    query = (
        db.query(Interview, Application, Candidate, JobRole.title, User, status_expr.label("computed_status"))
        .join(Application, Application.id == Interview.application_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .outerjoin(User, User.id == Interview.interviewer_id)
    )
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    if interviewer_id is not None:
        query = query.filter(Interview.interviewer_id == interviewer_id)
    if scheduling_method is not None:
        query = query.filter(Interview.scheduling_method == scheduling_method)
    if scheduled_after is not None:
        query = query.filter(Interview.scheduled_at >= datetime.combine(scheduled_after, time.min, tzinfo=timezone.utc))
    if scheduled_before is not None:
        query = query.filter(Interview.scheduled_at <= datetime.combine(scheduled_before, time.max, tzinfo=timezone.utc))
    if status is not None:
        query = query.filter(status_expr == status)
    return query


@router.get("/interviews", response_model=InterviewsListPage)
def list_all_interviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    job_role_id: Optional[uuid.UUID] = Query(None),
    interviewer_id: Optional[uuid.UUID] = Query(None),
    status: Optional[Literal["upcoming", "awaiting_feedback", "selected", "rejected"]] = Query(
        None, description=f"One of {INTERVIEW_STATUSES}"
    ),
    scheduling_method: Optional[Literal["manual", "auto"]] = Query(None),
    scheduled_after: Optional[date] = Query(None, description="Interviews scheduled on/after this date"),
    scheduled_before: Optional[date] = Query(None, description="Interviews scheduled on/before this date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per interview, across every job -- the data source for the Interview List
    page. Mirrors GET /candidates/applications's page/page_size/filter shape."""
    query = filtered_interviews_query(
        db,
        job_role_id=job_role_id,
        interviewer_id=interviewer_id,
        status=status,
        scheduling_method=scheduling_method,
        scheduled_after=scheduled_after,
        scheduled_before=scheduled_before,
    )
    total = query.count()
    rows = (
        query.order_by(Interview.scheduled_at.desc().nullslast())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        interview_row_to_item(interview, application, candidate, job_title, interviewer, computed_status)
        for interview, application, candidate, job_title, interviewer, computed_status in rows
    ]
    return InterviewsListPage(total=total, page=page, page_size=page_size, items=items)


@router.post("/applications/{application_id}/interviews", response_model=InterviewRead, status_code=201)
def schedule_interview(
    application_id: uuid.UUID,
    payload: InterviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "interviewer", "hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    if application.status not in SCHEDULABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Application must be HR-selected before an interview can be scheduled",
        )
    interviewer = None
    if payload.interviewer_id:
        interviewer = db.get(User, payload.interviewer_id)
        if not interviewer:
            raise HTTPException(status_code=404, detail="Interviewer not found")

    calendar_event = None
    if interviewer:
        calendar_event = _try_create_calendar_event(db, application, interviewer, payload.scheduled_at)

    interview = Interview(
        application_id=application.id,
        interviewer_id=payload.interviewer_id,
        scheduled_at=payload.scheduled_at,
        meeting_link=payload.meeting_link,
        calendar_event_id=calendar_event["event_id"] if calendar_event else None,
        calendar_link=calendar_event["html_link"] if calendar_event else None,
        scheduling_method="manual",
    )
    db.add(interview)

    previous_status = application.status
    application.status = "interview_scheduled"
    db.commit()
    db.refresh(interview)

    log_action(
        db,
        "interview",
        interview.id,
        "interview_scheduled",
        "system",
        {
            "application_id": str(application.id),
            "scheduled_at": payload.scheduled_at.isoformat(),
            "previous_status": previous_status,
        },
    )
    return interview


@router.get("/applications/{application_id}/interviews", response_model=list[InterviewRead])
def list_interviews(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    _get_application_or_404(db, application_id)
    return (
        db.query(Interview)
        .filter(Interview.application_id == application_id)
        .order_by(Interview.scheduled_at)
        .all()
    )


@router.get("/interviews/{interview_id}", response_model=InterviewRead)
def get_interview(
    interview_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return _get_interview_or_404(db, interview_id)


@router.patch("/interviews/{interview_id}/feedback", response_model=InterviewRead)
def submit_interview_feedback(
    interview_id: uuid.UUID,
    payload: InterviewFeedbackUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "interviewer", "hiring_manager", "admin")),
):
    interview = _get_interview_or_404(db, interview_id)
    application = _get_application_or_404(db, interview.application_id)
    assert_application_not_on_hold(application)
    updates = payload.model_dump(exclude_unset=True)
    decision = updates.pop("decision", None)

    if decision is not None:
        if application.status != "interview_scheduled":
            raise HTTPException(
                status_code=400,
                detail="Application is not awaiting an interview decision",
            )

    for field, value in updates.items():
        setattr(interview, field, value)

    if decision is not None:
        interview.decision = decision
        application.status = "interview_selected" if decision == "selected" else "interview_rejected"

    db.commit()
    db.refresh(interview)

    log_action(
        db,
        "interview",
        interview.id,
        "interview_feedback_recorded",
        "system",
        {**updates, "decision": decision},
    )
    return interview


@router.post("/applications/{application_id}/interview-questions", response_model=InterviewQuestionsResponse)
def generate_questions(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "interviewer", "hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    job = db.get(JobRole, application.job_role_id)
    if not job or not job.jd_text:
        raise HTTPException(status_code=400, detail="Job description not yet generated")

    missing_skills = application.missing_skills or []
    try:
        result = generate_interview_questions(job.jd_text, missing_skills)
    except InterviewQuestionGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_action(db, "application", application.id, "ai_interview_questions_generated", "system", result)
    return result
