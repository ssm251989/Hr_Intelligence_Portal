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
    # sync_interviewer_pool_job_titles' own summary -- shown alongside the tracker
    # validation so the Settings page can report both in one save, same pattern as
    # LocalImportSettingsSaveResult's jobs_considered/folders_created.
    interviewer_pool_jobs_considered: int
    interviewer_pool_rows_added: int


class ProposeInterviewSlotsResponse(BaseModel):
    """Result of emailing a candidate their interview slot options (Part 3) -- how many of
    the (up to 3) candidate-facing slots actually found a free interviewer and were offered,
    and when their confirmation links expire."""

    slots_offered: int
    expires_at: Optional[datetime] = None


class RetryNegotiationResponse(BaseModel):
    """Result of POST .../retry-negotiation. outcome mirrors attempt_auto_negotiate_
    interview_slots' own return value ("started" once a fresh interviewer offer went out,
    null on a fresh skip -- e.g. the mailbox issue that caused the original failure still
    isn't fixed). invalidated_stale_tokens is how many leftover NegotiationToken rows this
    call cleaned up before retrying, for the same visibility a recruiter previously only
    got by asking someone to check the database by hand. reason is the actual server-side
    cause whenever outcome is null (e.g. "HR mailbox's SMTP settings are not configured"),
    null whenever outcome is "started" -- lets the frontend show the real reason instead of
    generic fallback copy."""

    outcome: Optional[str] = None
    invalidated_stale_tokens: int
    reason: Optional[str] = None
