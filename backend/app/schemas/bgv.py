import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

BGV_DOC_TYPES = ("aadhaar", "pan", "degree", "experience")


class BgvDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    doc_type: str
    file_path: Optional[str] = None
    validation_status: str
    validator_output: Optional[dict] = None
    created_at: datetime


class BgvClearRequest(BaseModel):
    decision: Literal["clear", "reject"]
    notes: Optional[str] = None
    cleared_by: Optional[str] = None
