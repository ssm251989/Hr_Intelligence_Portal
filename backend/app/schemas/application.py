import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ApplicationCreate(BaseModel):
    job_role_id: uuid.UUID
    candidate_id: uuid.UUID
    expected_salary: Optional[float] = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_role_id: uuid.UUID
    candidate_id: uuid.UUID
    match_score: Optional[float] = None
    skill_match_pct: Optional[float] = None
    missing_skills: Optional[list] = None
    composite_score: Optional[float] = None
    ranking_score: Optional[float] = None
    ranking_rationale: Optional[str] = None
    status: str
    # Only meaningful while status == 'on_hold' (see app/candidates/hold.py) -- the status
    # to restore on resume. Null otherwise.
    previous_status: Optional[str] = None
    expected_salary: Optional[float] = None
    approved_salary: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class ShortlistDecisionRequest(BaseModel):
    decision: Literal["select", "reject"]
    notes: Optional[str] = None
    decided_by: Optional[str] = None
