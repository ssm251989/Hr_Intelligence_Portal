import uuid
from typing import Optional

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.hold import put_application_on_hold, resume_application_from_hold
from app.candidates.pipeline_actions import compute_next_actions
from app.core.crypto import decrypt
from app.core.database import get_db
from app.integrations.gmail import GmailError, send_email
from app.jobs.service import notify_job_owner_of_new_application
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.schemas.application import ApplicationCreate, ApplicationRead
from app.schemas.candidates_dashboard import (
    CandidateApplicationDetail,
    CandidateMessageRequest,
    CandidateMessageResponse,
    OtherApplicationItem,
)
from app.screening.service import attempt_auto_screen

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def create_application_record(
    db: Session, job: JobRole, candidate: Candidate, expected_salary: Optional[float] = None, actor: str = "system"
) -> Application:
    """The real "link a candidate to a job" logic -- shared by the authenticated POST
    /applications endpoint below and Part G's local-import scan (which auto-links each
    imported candidate to their own AI-suggested "Suitable For" job, see
    app/local_import/service.py, rather than a recruiter picking one manually here).
    """
    application = Application(
        job_role_id=job.id,
        candidate_id=candidate.id,
        expected_salary=expected_salary,
        status="received",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    log_action(db, "application", application.id, "application_created", actor, {"status": application.status})
    notify_job_owner_of_new_application(db, job, candidate)

    # Automatic screening (Part A): covers manual-upload and local-import candidates,
    # whose resume is typically already parsed by the time a job gets linked here (the
    # career-portal path instead becomes screenable when parsing completes afterward --
    # see candidates/router.py parse_and_apply_resume's own call to this same helper).
    attempt_auto_screen(db, application, actor)

    return application


@router.post("", response_model=ApplicationRead, status_code=201)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    job = db.get(JobRole, payload.job_role_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job role not found")
    candidate = db.get(Candidate, payload.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return create_application_record(db, job, candidate, expected_salary=payload.expected_salary)


@router.get("", response_model=list[ApplicationRead])
def list_applications(
    job_role_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Application)
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    return query.order_by(Application.created_at.desc()).all()


@router.get("/{application_id}/candidate-detail", response_model=CandidateApplicationDetail)
def get_candidate_application_detail(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    application = _get_application_or_404(db, application_id)
    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    other_rows = (
        db.query(Application, JobRole.title)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .filter(Application.candidate_id == candidate.id, Application.id != application_id)
        .order_by(Application.created_at.desc())
        .all()
    )

    return CandidateApplicationDetail(
        application=application,
        job_title=job.title if job else "Unknown role",
        candidate=candidate,
        next_actions=compute_next_actions(db, application),
        other_applications=[
            OtherApplicationItem(
                application_id=other_app.id,
                job_role_id=other_app.job_role_id,
                job_title=title,
                status=other_app.status,
                applied_on=other_app.created_at,
            )
            for other_app, title in other_rows
        ],
    )


@router.post("/{application_id}/hold", response_model=ApplicationRead)
def put_application_on_hold_endpoint(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Any non-terminal status -> on_hold. Blocked from the five terminal statuses
    (hr_rejected, interview_rejected, salary_rejected, bgv_rejected, onboarding_completed)
    -- nothing further happens to those applications, so "pausing" one is meaningless."""
    application = _get_application_or_404(db, application_id)
    put_application_on_hold(db, application, current_user.email)
    return application


@router.post("/{application_id}/resume", response_model=ApplicationRead)
def resume_application_from_hold_endpoint(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """on_hold -> whatever status it was paused from."""
    application = _get_application_or_404(db, application_id)
    resume_application_from_hold(db, application, current_user.email)
    return application


@router.delete("/{application_id}", status_code=204)
def delete_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    """Only allowed at status='received' -- nothing real (screening, interviews, salary,
    BGV, an offer) has happened to the pipeline yet, so there's nothing downstream to
    orphan. Same safety principle as app/jobs/router.py delete_job blocking any job that
    has ever been published."""
    application = _get_application_or_404(db, application_id)
    if application.status != "received":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete an application with status '{application.status}'. "
            "Only applications still at 'received' can be deleted.",
        )
    log_action(db, "application", application.id, "application_deleted", current_user.email, {"status": application.status})
    db.delete(application)
    db.commit()


@router.post("/{application_id}/message", response_model=CandidateMessageResponse)
def message_candidate(
    application_id: uuid.UUID,
    payload: CandidateMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Sends a real email to the candidate via the current user's connected Gmail
    (the same 'google' UserIntegration used for Calendar). There is no separate bypass
    here -- if the recruiter hasn't connected Google, this fails the same way any other
    Gmail-backed action in the app does, and the frontend gates the button on connection
    status beforehand (see app/jobs/service.py's notification pattern)."""
    application = _get_application_or_404(db, application_id)
    candidate = db.get(Candidate, application.candidate_id)
    if not candidate or not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email on file")

    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == current_user.id, UserIntegration.provider == "google")
        .first()
    )
    if not integration:
        raise HTTPException(status_code=400, detail="Connect Google in Settings to send email to candidates")

    try:
        send_email(decrypt(integration.refresh_token), to=candidate.email, subject=payload.subject, body=payload.body)
    except (GmailError, InvalidToken) as exc:
        detail = str(exc) or "Stored Google refresh token could not be decrypted"
        raise HTTPException(status_code=502, detail=detail) from exc

    log_action(
        db,
        "application",
        application.id,
        "candidate_email_sent",
        current_user.email,
        {"to": candidate.email, "subject": payload.subject},
    )
    return CandidateMessageResponse(sent=True, to=candidate.email)
