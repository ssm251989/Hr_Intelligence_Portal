"""The single shared, org-level HR mailbox ("CTDHR") -- plain SMTP/IMAP credentials
(universal across providers: Gmail, Outlook, Yahoo, anything), not an OAuth connection.
Every automated/manual HR email in this app (interview negotiation, candidate messages,
new-application notifications) sends through send_hr_email below. Calendar event creation
is a completely separate feature and is untouched: it still always uses the responsible
recruiter/interviewer's own personal Google OAuth UserIntegration.
"""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.models.hr_integration import HrIntegration

# Real-world SMTP servers can hang rather than refuse outright on a bad host/port/firewall
# combination -- a fixed ceiling so a single misconfigured mailbox can never hang whatever
# request or scheduled job triggered the send indefinitely.
SMTP_TIMEOUT_SECONDS = 15


class SmtpError(Exception):
    """Raised for any reason send_hr_email couldn't actually deliver -- an undecryptable
    stored password, a connection/auth failure, or the SMTP server rejecting the message.
    Callers catch this exactly the way they used to catch (GmailError, InvalidToken)."""


@dataclass
class EmailAttachment:
    """One file to attach to an outgoing HR email -- e.g. the .ics calendar invite the
    pick-2-of-3 negotiation mechanic's confirmation step generates (see
    app/integrations/ics.py, app/interview_scheduling/negotiation.py _finalize).
    `content` is attached as-is (bytes, not re-encoded through a str content manager) so a
    format with meaningful exact bytes -- like .ics's required CRLF line endings -- survives
    unchanged."""

    filename: str
    content: bytes
    maintype: str
    subtype: str


def get_hr_integration(db: Session) -> HrIntegration:
    """The singleton hr_integrations row (id=1). Defensively creates it (empty) if somehow
    missing, same "test DB that ran migrations before this table existed" defensiveness as
    get_interview_scheduling_settings, rather than crashing outright.

    Null/absent SMTP or IMAP fields mean that side of the real CTDHR mailbox hasn't been
    configured via Settings yet -- every caller checks is_smtp_configured/is_imap_
    configured explicitly and skips gracefully (same "actor hasn't connected Google"
    pattern this app's email-sending already used before this integration existed), never
    a hard failure.
    """
    row = db.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def is_smtp_configured(hr_integration: HrIntegration) -> bool:
    return bool(hr_integration.smtp_host and hr_integration.smtp_username and hr_integration.smtp_password)


def send_hr_email(
    hr_integration: HrIntegration, *, to: str, subject: str, body: str,
    html_body: Optional[str] = None, attachment: Optional[EmailAttachment] = None,
) -> None:
    """Sends one email via the shared HR mailbox's SMTP credentials. `hr_module_email`,
    when configured, is added as both Reply-To and BCC on every send (a no-op, neither
    header added, when left blank) -- otherwise this is a plain, provider-agnostic SMTP
    send (STARTTLS when use_tls is set, exactly the fields configured in Settings).

    `body` is always sent as the plain-text part -- required even when `html_body` is
    given, since it's also what every plain-text-only recipient (and every mail client
    that fails to render the HTML part) actually sees. `html_body`, when given, is added
    via add_alternative (not set_content) -- the standard multipart/alternative shape,
    where a client picks whichever of the two parts it prefers/supports; it never replaces
    the plain-text part outright.

    Raises SmtpError for any reason the send didn't happen -- an undecryptable stored
    password, or any smtplib/connection failure -- so every caller can handle both cases
    with the exact same except clause, unlike the old two-exception-type Gmail pattern.
    """
    # Part 20.2b: a TEST (dummy) mailbox address never gets a real email -- test inbox (+ mailpit in dev)
    from app.employees.test_inbox import intercept_single

    if intercept_single(to, subject=subject, text=body, html=html_body, from_address=hr_integration.from_address or hr_integration.smtp_username):
        return
    try:
        password = decrypt(hr_integration.smtp_password)
    except InvalidToken as exc:
        raise SmtpError("Stored SMTP password could not be decrypted") from exc

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = hr_integration.from_address or hr_integration.smtp_username
    message["To"] = to
    recipients = [to]
    if hr_integration.hr_module_email:
        message["Reply-To"] = hr_integration.hr_module_email
        message["Bcc"] = hr_integration.hr_module_email
        recipients.append(hr_integration.hr_module_email)
    message.set_content(body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
    if attachment is not None:
        message.add_attachment(
            attachment.content, maintype=attachment.maintype, subtype=attachment.subtype,
            filename=attachment.filename,
        )

    from app.core.config import settings as _settings

    try:
        if _settings.DEV_MAIL_CAPTURE:  # development only: every email goes to the local capture (mailpit), never out
            host, _, port = _settings.DEV_MAIL_CAPTURE.partition(":")
            with smtplib.SMTP(host, int(port or 1025), timeout=SMTP_TIMEOUT_SECONDS) as server:
                server.send_message(message, to_addrs=recipients)
            return
        with smtplib.SMTP(hr_integration.smtp_host, hr_integration.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            if hr_integration.use_tls:
                server.starttls()
            server.login(hr_integration.smtp_username, password)
            server.send_message(message, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as exc:
        raise SmtpError(str(exc) or "Failed to send email via the HR mailbox's SMTP connection") from exc


def encrypted_smtp_password(raw_password: Optional[str], existing: Optional[str]) -> Optional[str]:
    """Settings-save helper: encrypts a freshly-submitted password, or -- when the admin
    left the password field blank (the standard "don't ask to retype a secret every time"
    convention) -- keeps whatever was already stored. `existing` is the row's current
    (already-encrypted) value."""
    if raw_password:
        return encrypt(raw_password)
    return existing
