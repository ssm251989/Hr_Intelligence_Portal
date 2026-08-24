import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.database import get_db
from app.integrations.hr_email import get_hr_integration, is_smtp_configured, SmtpError
from app.interview_scheduling.confirmation import propose_interview_slots
from app.interview_scheduling.negotiation import check_retry_eligibility, retry_negotiation
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.interview_scheduling.tracker import ensure_tracker_file, sync_interviewer_pool_job_titles
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.interview_scheduling import (
    InterviewSchedulingSettingsRead,
    InterviewSchedulingSettingsSaveResult,
    InterviewSchedulingSettingsUpdate,
    ProposeInterviewSlotsResponse,
    RetryNegotiationResponse,
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
    patching an existing file without touching any data already in it. Also immediately
    syncs the Interviewer Pool sheet's Job Title column (see tracker.py
    sync_interviewer_pool_job_titles) against every currently published/
    ready_for_publishing job, same "sync right away, not just on the next natural
    touchpoint" reasoning as app/local_import/router.py's update_settings -- this feature
    has no scheduler of its own to piggyback on, so the same sync also runs every time
    propose_interview_slots is called (see app/interview_scheduling/confirmation.py), the
    one recurring moment the sheet is actually read from."""
    settings_row = get_interview_scheduling_settings(db)
    settings_row.tracker_path = payload.tracker_path
    db.commit()
    db.refresh(settings_row)

    validation = ensure_tracker_file(Path(payload.tracker_path))
    pool_sync = sync_interviewer_pool_job_titles(db, Path(payload.tracker_path))

    return InterviewSchedulingSettingsSaveResult(
        tracker_path=settings_row.tracker_path,
        updated_at=settings_row.updated_at,
        validation=TrackerValidationResult(**validation),
        interviewer_pool_jobs_considered=pool_sync["jobs_considered"],
        interviewer_pool_rows_added=pool_sync["rows_added"],
    )


@router.post("/applications/{application_id}/propose-slots", response_model=ProposeInterviewSlotsResponse)
def propose_slots(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Kicks off Part 3: runs the interviewer-selection logic for up to 3 candidate-facing
    slots and emails the candidate a distinct confirmation link per slot that actually found
    someone free, via the shared, org-level HR mailbox's SMTP settings (app/integrations/
    hr_email.py) -- same sender pattern as /applications/{id}/message."""
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

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        raise HTTPException(status_code=400, detail="Configure the HR mailbox's SMTP settings to send interview slot emails")

    try:
        result = propose_interview_slots(
            db, application, tracker_path=settings_row.tracker_path, candidate=candidate, job=job,
            hr_integration=hr_integration, actor=current_user.email,
        )
    except SmtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result["slots_offered"] == 0:
        raise HTTPException(
            status_code=409,
            detail="No interviewer availability found for any of the proposed slots -- check the "
            "Interviewer Pool and connected Google Calendars",
        )

    return ProposeInterviewSlotsResponse(slots_offered=result["slots_offered"], expires_at=result["expires_at"])


@router.post("/applications/{application_id}/retry-negotiation", response_model=RetryNegotiationResponse)
def retry_negotiation_endpoint(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Manual escape hatch for an application stuck at Shortlisted ('hr_selected') after
    attempt_auto_negotiate_interview_slots failed (e.g. a send error) -- deliberately NOT a
    status change, so this bypasses app.shortlisting.service.update_shortlist_status's
    terminal-SHORTLISTED rule entirely rather than asking a recruiter to re-decide a
    shortlisting call that was never actually reversed. Replaces the one-off manual
    NegotiationToken cleanup this exact stuck-application failure mode used to require by
    hand (see app.interview_scheduling.negotiation.check_retry_eligibility/
    retry_negotiation for the eligibility rules and cleanup this now does automatically).
    """
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    ineligible_reason = check_retry_eligibility(db, application)
    if ineligible_reason:
        raise HTTPException(status_code=409, detail=ineligible_reason)

    outcome, invalidated_count, reason = retry_negotiation(db, application, current_user)
    return RetryNegotiationResponse(outcome=outcome, invalidated_stale_tokens=invalidated_count, reason=reason)
