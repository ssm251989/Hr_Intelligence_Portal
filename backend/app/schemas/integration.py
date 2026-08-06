from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IntegrationStatus(BaseModel):
    connected: bool
    connected_at: Optional[datetime] = None


class GoogleAuthUrl(BaseModel):
    auth_url: str


class DocuSignAuthUrl(BaseModel):
    auth_url: str
