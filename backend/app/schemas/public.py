import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PublicJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    experience_level: Optional[str] = None
    skills: Optional[list[str]] = None
    jd_text: Optional[str] = None


class PublicApplicationSubmitResponse(BaseModel):
    application_id: uuid.UUID
    status: str
