import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PublicJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    experience_min_years: Optional[float] = None
    experience_max_years: Optional[float] = None
    technical_skills_must_have: Optional[list[str]] = None
    technical_skills_good_to_have: Optional[list[str]] = None
    soft_skills_must_have: Optional[list[str]] = None
    soft_skills_good_to_have: Optional[list[str]] = None
    jd_text: Optional[str] = None


class PublicApplicationSubmitResponse(BaseModel):
    application_id: uuid.UUID
    status: str
