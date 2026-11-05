from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Bounds for scan_interval_minutes: frequent enough to matter (5 min) but never so tight it
# could overlap a still-running scan/hammer the Anthropic Batches API, and never so loose it
# stops being "auto" in any practical sense (24h).
MIN_SCAN_INTERVAL_MINUTES = 5
MAX_SCAN_INTERVAL_MINUTES = 1440


class LocalImportSettingsRead(BaseModel):
    ready_to_upload_root: Optional[str] = None
    already_uploaded_root: Optional[str] = None
    scan_interval_minutes: int = 30
    updated_at: Optional[datetime] = None


class LocalImportSettingsUpdate(BaseModel):
    """All three fields are required together -- there's no meaningful "configure just one
    root" state, since the scan needs both paths to do anything, and the interval is saved
    on the same "Local Import" wizard step. Saving triggers an immediate job-folder sync
    (see app/local_import/job_folders.py sync_job_folders), reported back in
    LocalImportSettingsSaveResult below."""

    ready_to_upload_root: str
    already_uploaded_root: str
    scan_interval_minutes: int = Field(ge=MIN_SCAN_INTERVAL_MINUTES, le=MAX_SCAN_INTERVAL_MINUTES)

    @field_validator("ready_to_upload_root", "already_uploaded_root")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Path must not be blank")
        return stripped


class LocalImportSettingsSaveResult(LocalImportSettingsRead):
    """LocalImportSettingsRead plus the immediate job-folder sync's own summary -- the
    wizard's configure step shows this directly rather than making a second call."""

    jobs_considered: int
    folders_created: int
