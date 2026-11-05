from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IntegrationStatus(BaseModel):
    connected: bool
    connected_at: Optional[datetime] = None
    # Only meaningful when connected=True and the provider's credential actually expires
    # (LinkedIn) -- null for providers that don't track expiry (Google, DocuSign).
    expired: Optional[bool] = None


class GoogleAuthUrl(BaseModel):
    auth_url: str


class DocuSignAuthUrl(BaseModel):
    auth_url: str


class LinkedInAuthUrl(BaseModel):
    auth_url: str
