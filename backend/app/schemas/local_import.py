from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class LocalImportSettingsRead(BaseModel):
    ready_to_upload_root: Optional[str] = None
    already_uploaded_root: Optional[str] = None
    updated_at: Optional[datetime] = None


class LocalImportSettingsUpdate(BaseModel):
    """Both paths are required together -- there's no meaningful "configure just one root"
    state, since the scan needs both to do anything. Saving triggers an immediate job-folder
    sync (see app/local_import/job_folders.py sync_job_folders), reported back in
    LocalImportSettingsSaveResult below."""

    ready_to_upload_root: str
    already_uploaded_root: str

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
