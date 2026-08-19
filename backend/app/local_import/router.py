from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.local_import.job_folders import sync_job_folders
from app.local_import.scheduler import reschedule_scan_interval
from app.local_import.service import run_local_import_scan
from app.local_import.storage import get_local_import_settings
from app.models.user import User
from app.schemas.local_import import LocalImportSettingsRead, LocalImportSettingsSaveResult, LocalImportSettingsUpdate

router = APIRouter(prefix="/local-import", tags=["local-import"])


@router.get("/settings", response_model=LocalImportSettingsRead)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    return get_local_import_settings(db)


@router.put("/settings", response_model=LocalImportSettingsSaveResult)
def update_settings(
    payload: LocalImportSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Saved via the "Import from Source" wizard's Local Import configure step. Immediately
    syncs job folders under both roots (creates one subfolder per currently published/
    ready_for_publishing job -- see app/local_import/job_folders.py) so the wizard can show
    the recruiter exactly what got created, right away, rather than waiting for the next
    scheduled scan to do it. Also reschedules the running scheduler's interval immediately
    (see app/local_import/scheduler.py reschedule_scan_interval) -- a changed interval takes
    effect right away, no server restart required."""
    settings_row = get_local_import_settings(db)
    settings_row.ready_to_upload_root = payload.ready_to_upload_root
    settings_row.already_uploaded_root = payload.already_uploaded_root
    settings_row.scan_interval_minutes = payload.scan_interval_minutes
    db.commit()
    db.refresh(settings_row)

    sync_result = sync_job_folders(
        db, Path(payload.ready_to_upload_root), Path(payload.already_uploaded_root)
    )
    reschedule_scan_interval(settings_row.scan_interval_minutes)

    return LocalImportSettingsSaveResult(
        ready_to_upload_root=settings_row.ready_to_upload_root,
        already_uploaded_root=settings_row.already_uploaded_root,
        scan_interval_minutes=settings_row.scan_interval_minutes,
        updated_at=settings_row.updated_at,
        **sync_result,
    )


@router.post("/run-now")
def run_now(current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin"))):
    """Manually triggers the same scan the scheduler runs on its configured interval (app/
    local_import/scheduler.py) -- for real functional testing without waiting for a real
    scheduled tick, or for an admin who doesn't want to wait for the next one. Runs
    synchronously (a bounded wait on the AI batch, see service.py's
    BATCH_POLL_TIMEOUT_SECONDS) and returns the same summary dict the scheduled run logs to
    audit_log."""
    return run_local_import_scan(actor=current_user.email)
