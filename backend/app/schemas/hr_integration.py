import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HrIntegrationRead(BaseModel):
    """The shared HR mailbox's current settings -- smtp_password is deliberately never
    returned (same "never send a secret back" convention as the old OAuth refresh token),
    only smtp_configured/imap_configured booleans saying whether enough of each side is
    filled in to actually work."""

    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    use_tls: Optional[bool] = None
    smtp_username: Optional[str] = None
    from_address: Optional[str] = None
    hr_module_email: Optional[str] = None
    smtp_configured: bool

    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    use_ssl: Optional[bool] = None
    imap_configured: bool


class HrIntegrationUpdate(BaseModel):
    """A settings-save body -- every field is optional and only ever applied when present
    in the request (see app/hr_inbox/router.py's exclude_unset). smtp_password specifically
    also treats an omitted/blank value as "leave the currently-stored password alone,"
    the standard "don't ask to retype a secret every time" convention -- see
    app.integrations.hr_email.encrypted_smtp_password."""

    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    use_tls: Optional[bool] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    from_address: Optional[str] = None
    hr_module_email: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    use_ssl: Optional[bool] = None


class SendTestEmailRequest(BaseModel):
    to: str


class SendTestEmailResult(BaseModel):
    sent: bool
    detail: Optional[str] = None


class TestImapConnectionResult(BaseModel):
    connected: bool
    detail: Optional[str] = None


class HrInboundEmailRead(BaseModel):
    id: uuid.UUID
    from_address: str
    to_address: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    received_at: Optional[datetime] = None
    message_id: Optional[str] = None
    matched_candidate_id: Optional[uuid.UUID] = None
    matched_candidate_name: Optional[str] = None
    matched_application_id: Optional[uuid.UUID] = None
    matched_job_title: Optional[str] = None
    created_at: datetime


class HrInboxListPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[HrInboundEmailRead]
