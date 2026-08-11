import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    resume_path: Optional[str] = None
    photo_path: Optional[str] = None
    # Computed on every read from full_name (see app/candidates/gender_inference.py), never
    # persisted -- purely a fallback-avatar hint for the frontend, "male"/"female"/None.
    inferred_gender: Optional[str] = None
    parsed_fields: Optional[dict] = None
    source: str
    created_at: datetime


class CandidateUpdate(BaseModel):
    """Basic contact info only -- name/email/phone. Everything else about a candidate
    (resume, photo, parsed fields, source) comes from an upload/import/parse, not manual
    editing."""

    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
