"""Capability interfaces (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 1) -- every provider
adapter (platform/connectors/providers/*) implements one or more of these. `typing.Protocol`
(structural typing), not ABC: an adapter satisfies a capability by having the right
methods, no explicit inheritance required -- mirrors how loosely this codebase's own
existing integration modules (hr_email.py, imap_poll.py, docusign.py, ...) were never
written against a shared base class either.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class ProviderResult:
    success: bool
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class OutboundEmail:
    to: list[str]
    subject: str
    body_text: str
    body_html: Optional[str] = None
    cc: Optional[list[str]] = None
    bcc: Optional[list[str]] = None
    reply_to: Optional[str] = None
    attachments: Optional[list[dict]] = None  # {filename, content: bytes, maintype, subtype}


@dataclass
class InboundEmail:
    from_address: str
    to_address: str
    subject: str
    body_text: str
    message_id: str
    in_reply_to: Optional[str] = None
    received_at: Optional[datetime] = None
    attachments: Optional[list[dict]] = None


@runtime_checkable
class EmailSender(Protocol):
    def send(self, msg: OutboundEmail) -> ProviderResult: ...


@runtime_checkable
class EmailReceiver(Protocol):
    def poll(self, since: Optional[datetime]) -> list[InboundEmail]: ...


@runtime_checkable
class CalendarProvider(Protocol):
    def free_busy(self, identity: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...
    def create_event(self, **kwargs: Any) -> ProviderResult: ...
    def update_event(self, event_id: str, **kwargs: Any) -> ProviderResult: ...
    def cancel_event(self, event_id: str) -> ProviderResult: ...


@runtime_checkable
class IcsOnlyCalendar(Protocol):
    """No external account -- generates a .ics attachment only (this app's current
    interview-confirmation behavior, app/integrations/ics.py)."""

    def build_ics(self, **kwargs: Any) -> bytes: ...


@runtime_checkable
class SmsSender(Protocol):
    def send(self, to: str, body: str) -> ProviderResult: ...


@runtime_checkable
class WhatsAppSender(Protocol):
    def send(self, to: str, template_name: str, params: dict) -> ProviderResult: ...


@runtime_checkable
class ChatNotifier(Protocol):
    def post(self, channel: str, text: str) -> ProviderResult: ...


@runtime_checkable
class StorageProvider(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> ProviderResult: ...
    def get(self, key: str) -> bytes: ...
    def signed_url(self, key: str, expires_in_seconds: int) -> str: ...
    def delete(self, key: str) -> ProviderResult: ...


@runtime_checkable
class LlmProvider(Protocol):
    def complete(self, *, system: str, messages: list[dict], model: str, **kwargs: Any) -> dict: ...
    def embed(self, texts: list[str], model: str) -> list[list[float]]: ...


@runtime_checkable
class ESignProvider(Protocol):
    def create_envelope(self, *, document_bytes: bytes, signer_email: str, signer_name: str, **kwargs: Any) -> ProviderResult: ...
    def status(self, envelope_id: str) -> str: ...
    def download(self, envelope_id: str) -> bytes: ...


@runtime_checkable
class BgvProvider(Protocol):
    def initiate(self, *, candidate: dict, package: str) -> ProviderResult: ...
    def status(self, case_id: str) -> str: ...
    def report(self, case_id: str) -> bytes: ...


@runtime_checkable
class JobBoardPublisher(Protocol):
    def publish(self, job: dict) -> ProviderResult: ...
    def unpublish(self, external_id: str) -> ProviderResult: ...
    def fetch_applicants(self, external_id: str) -> list[dict]: ...


@runtime_checkable
class BiometricSource(Protocol):
    def pull_punches(self, since: datetime) -> list[dict]: ...


@runtime_checkable
class IdentityProvider(Protocol):
    """SAML2/OIDC -- interface only; SSO is a later part."""

    def authorize_url(self, state: str) -> str: ...
    def exchange(self, code: str) -> dict: ...


@runtime_checkable
class HrisSync(Protocol):
    def import_records(self, source: bytes, content_type: str) -> list[dict]: ...


@runtime_checkable
class WebhookTarget(Protocol):
    def send(self, url: str, payload: dict, secret: str) -> ProviderResult: ...


@runtime_checkable
class VideoMeeting(Protocol):
    def create_meeting(self, *, topic: str, start: datetime, duration_minutes: int, **kwargs: Any) -> ProviderResult: ...
