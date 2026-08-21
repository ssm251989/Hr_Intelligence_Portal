"""The single shared, org-level HR mailbox ("CTDHR") -- plain SMTP/IMAP credentials
(universal across providers: Gmail, Outlook, Yahoo, anything), not an OAuth connection.
Every automated/manual HR email in this app (interview negotiation, candidate messages,
new-application notifications) sends through send_hr_email below. Calendar event creation
is a completely separate feature and is untouched: it still always uses the responsible
recruiter/interviewer's own personal Google OAuth UserIntegration.
"""

import smtplib
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


def send_hr_email(hr_integration: HrIntegration, *, to: str, subject: str, body: str) -> None:
    """Sends one email via the shared HR mailbox's SMTP credentials. `hr_module_email`,
    when configured, is added as both Reply-To and BCC on every send (a no-op, neither
    header added, when left blank) -- otherwise this is a plain, provider-agnostic SMTP
    send (STARTTLS when use_tls is set, exactly the fields configured in Settings).

    Raises SmtpError for any reason the send didn't happen -- an undecryptable stored
    password, or any smtplib/connection failure -- so every caller can handle both cases
    with the exact same except clause, unlike the old two-exception-type Gmail pattern.
    """
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

    try:
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
