from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class InterviewSchedulingSettingsRead(BaseModel):
    tracker_path: Optional[str] = None
    updated_at: Optional[datetime] = None


class InterviewSchedulingSettingsUpdate(BaseModel):
    tracker_path: str

    @field_validator("tracker_path")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Path must not be blank")
        return stripped


class TrackerValidationResult(BaseModel):
    """What ensure_tracker_file actually did to the workbook at this path -- shown on the
    Settings page so a recruiter can see whether their existing tracker was left untouched
    or patched with missing sheets/columns."""

    created: bool
    sheets_added: list[str]
    columns_added: dict[str, list[str]]


class InterviewSchedulingSettingsSaveResult(InterviewSchedulingSettingsRead):
    validation: TrackerValidationResult
