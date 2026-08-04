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
    resume_path: Optional[str] = None
    parsed_fields: Optional[dict] = None
    created_at: datetime
