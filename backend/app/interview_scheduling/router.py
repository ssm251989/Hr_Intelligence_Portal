from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.interview_scheduling.tracker import ensure_tracker_file
from app.models.user import User
from app.schemas.interview_scheduling import (
    InterviewSchedulingSettingsRead,
    InterviewSchedulingSettingsSaveResult,
    InterviewSchedulingSettingsUpdate,
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
