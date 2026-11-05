import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: Optional[str] = None
    # fix 2026-10-05: HR's corrected names (null = not set; the profile then shows the guess from names_of())
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    preferred_name: Optional[str] = None
    # computed on read (app/candidates/names.py): {"first_name", "last_name", "preferred_name", "source": hr | resume | none}
    name_parts: Optional[dict] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tags: list[str] = []  # Part 18.10
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
    first_name: Optional[str] = Field(None, max_length=120)
    last_name: Optional[str] = Field(None, max_length=120)
    preferred_name: Optional[str] = Field(None, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
