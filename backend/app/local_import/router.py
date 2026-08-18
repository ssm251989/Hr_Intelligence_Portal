from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.local_import.service import run_local_import_scan
from app.models.user import User

router = APIRouter(prefix="/local-import", tags=["local-import"])


@router.post("/run-now")
def run_now(current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin"))):
    """Manually triggers the same scan the hourly scheduler runs (app/local_import/
    scheduler.py) -- for real functional testing without waiting for a real hourly tick, or
    for an admin who doesn't want to wait for the next scheduled one. Runs synchronously
    (a bounded wait on the AI batch, see service.py's BATCH_POLL_TIMEOUT_SECONDS) and
    returns the same summary dict the scheduled run logs to audit_log."""
    return run_local_import_scan(actor=current_user.email)
