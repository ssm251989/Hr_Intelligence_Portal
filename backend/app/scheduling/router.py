import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.interview_question_generator import generate_interview_questions
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.models.application import Application
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.interview import (
    InterviewCreate,
    InterviewFeedbackUpdate,
    InterviewQuestionsResponse,
    InterviewRead,
)

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


@router.post("/applications/{application_id}/interviews", response_model=InterviewRead, status_code=201)
def schedule_interview(
    application_id: uuid.UUID,
    payload: InterviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "interviewer", "hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status not in SCHEDULABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Application must be HR-selected before an interview can be scheduled",
        )
    if payload.interviewer_id and not db.get(User, payload.interviewer_id):
        raise HTTPException(status_code=404, detail="Interviewer not found")

    interview = Interview(
        application_id=application.id,
        interviewer_id=payload.interviewer_id,
        scheduled_at=payload.scheduled_at,
        meeting_link=payload.meeting_link,
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
    updates = payload.model_dump(exclude_unset=True)
    decision = updates.pop("decision", None)

    application = None
    if decision is not None:
        application = _get_application_or_404(db, interview.application_id)
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
    job = db.get(JobRole, application.job_role_id)
    if not job or not job.jd_text:
        raise HTTPException(status_code=400, detail="Job description not yet generated")

    missing_skills = application.missing_skills or []
    result = generate_interview_questions(job.jd_text, missing_skills)

    log_action(db, "application", application.id, "ai_interview_questions_generated", "system", result)
    return result
