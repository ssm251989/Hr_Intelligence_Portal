import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OfferGenerateRequest(BaseModel):
    start_date: str
    reporting_manager_name: Optional[str] = None


class OfferSendRequest(BaseModel):
    docusign_envelope_id: Optional[str] = None


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    offer_letter_text: Optional[str] = None
    docusign_envelope_id: Optional[str] = None
    signed: bool
    onboarding_status: str
    created_at: datetime
