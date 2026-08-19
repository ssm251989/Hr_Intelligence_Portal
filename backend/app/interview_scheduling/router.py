import uuid
from pathlib import Path

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.crypto import decrypt
from app.core.database import get_db
from app.integrations.gmail import GmailError
from app.interview_scheduling.confirmation import propose_interview_slots
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.interview_scheduling.tracker import ensure_tracker_file
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.schemas.interview_scheduling import (
    InterviewSchedulingSettingsRead,
    InterviewSchedulingSettingsSaveResult,
    InterviewSchedulingSettingsUpdate,
    ProposeInterviewSlotsResponse,
    TrackerValidationResult,
)

router = APIRouter(prefix="/interview-scheduling", tags=["interview-scheduling"])


@router.get("/settings", response_model=InterviewSchedulingSettingsRead)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    return get_interview_scheduling_settings(db)


@router.put("/settings", response_model=InterviewSchedulingSettingsSaveResult)
def update_settings(
    payload: InterviewSchedulingSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Saved via the Settings page's Interview Scheduling section. Immediately ensures the
    tracker workbook exists with the expected sheets/columns (see app/interview_scheduling/
    tracker.py ensure_tracker_file) -- creating it fresh if the path is new, or validating/
    patching an existing file without touching any data already in it."""
    settings_row = get_interview_scheduling_settings(db)
    settings_row.tracker_path = payload.tracker_path
    db.commit()
    db.refresh(settings_row)

    validation = ensure_tracker_file(Path(payload.tracker_path))

    return InterviewSchedulingSettingsSaveResult(
        tracker_path=settings_row.tracker_path,
        updated_at=settings_row.updated_at,
        validation=TrackerValidationResult(**validation),
    )


@router.post("/applications/{application_id}/propose-slots", response_model=ProposeInterviewSlotsResponse)
def propose_slots(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Kicks off Part 3: runs the interviewer-selection logic for up to 3 candidate-facing
    slots and emails the candidate a distinct confirmation link per slot that actually found
    someone free, via the current user's own connected Gmail -- same sender pattern as
    /applications/{id}/message."""
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_not_on_hold(application)
    if application.status != "hr_selected":
        raise HTTPException(
            status_code=400,
            detail="Application must be HR-selected before interview slots can be proposed",
        )

    settings_row = get_interview_scheduling_settings(db)
    if not settings_row.tracker_path:
        raise HTTPException(
            status_code=400,
            detail="Configure the Interview Scheduling tracker path in Settings before proposing slots",
        )

    candidate = db.get(Candidate, application.candidate_id)
    if not candidate or not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email on file")
    job = db.get(JobRole, application.job_role_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == current_user.id, UserIntegration.provider == "google")
        .first()
    )
    if not integration:
        raise HTTPException(status_code=400, detail="Connect Google in Settings to send interview slot emails")

    try:
        result = propose_interview_slots(
            db, application, tracker_path=settings_row.tracker_path, candidate=candidate, job=job,
            sender_refresh_token=decrypt(integration.refresh_token), actor=current_user.email,
        )
    except (GmailError, InvalidToken) as exc:
        detail = str(exc) or "Stored Google refresh token could not be decrypted"
        raise HTTPException(status_code=502, detail=detail) from exc

    if result["slots_offered"] == 0:
        raise HTTPException(
            status_code=409,
            detail="No interviewer availability found for any of the proposed slots -- check the "
            "Interviewer Pool and connected Google Calendars",
        )

    return ProposeInterviewSlotsResponse(slots_offered=result["slots_offered"], expires_at=result["expires_at"])
