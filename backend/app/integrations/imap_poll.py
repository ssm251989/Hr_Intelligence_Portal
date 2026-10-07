"""The shared HR mailbox's incoming side -- an IMAP poll (checked every 30 minutes, see
app/local_import/scheduler.py) that fetches new mail, dedupes it, and tries to match each
sender against a real Candidate. Same universal-provider goal as the SMTP send side
(app/integrations/hr_email.py): plain IMAP credentials work with Gmail, Outlook, Yahoo, or
any other provider, no OAuth.

Two independent lines of defense against reprocessing the same message twice:
  1. imap_last_uid on HrIntegration -- the poll's own checkpoint, so each 30-minute tick
     only ever asks the server for UIDs strictly after the last one it already saw.
  2. HrInboundEmail.message_id, unique -- a second check at insert time, since the
     checkpoint alone can't protect against a poll that stored a row but crashed before
     advancing imap_last_uid (the next poll would re-fetch that UID; the message_id check
     catches it there).

A match (From address against Candidate.email, case-insensitive) also gets surfaced on
that candidate's existing Activity timeline via a normal audit_log entry (entity_type=
"candidate") -- see app/reports/router.py get_candidate_timeline, which already unions in
every audit_log row for that candidate id. No new frontend display was built for this;
this reuses exactly what's already there.
"""

import email
import email.policy
import email.utils
import imaplib
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.crypto import decrypt
from app.integrations.hr_email import get_hr_integration
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.hr_integration import HrIntegration

logger = logging.getLogger(__name__)

# Same reasoning as SMTP_TIMEOUT_SECONDS in hr_email.py -- a fixed ceiling so a
# misconfigured/unreachable IMAP host can never hang the poll (or the "Test IMAP
# connection" button's request) indefinitely.
IMAP_TIMEOUT_SECONDS = 15


class ImapError(Exception):
    """Raised for any reason a poll or connection test couldn't actually check the
    mailbox -- an undecryptable stored password, a connection/login failure, or the
    server rejecting a command."""


def is_imap_configured(hr_integration: HrIntegration) -> bool:
    return bool(hr_integration.imap_host and hr_integration.smtp_username and hr_integration.smtp_password)


def _connect(hr_integration: HrIntegration) -> imaplib.IMAP4:
    try:
        password = decrypt(hr_integration.smtp_password)
    except InvalidToken as exc:
        raise ImapError("Stored SMTP/IMAP password could not be decrypted") from exc

    imap_cls = imaplib.IMAP4_SSL if hr_integration.use_ssl else imaplib.IMAP4
    try:
        connection = imap_cls(hr_integration.imap_host, hr_integration.imap_port, timeout=IMAP_TIMEOUT_SECONDS)
        connection.login(hr_integration.smtp_username, password)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise ImapError(str(exc) or "Failed to connect to the HR mailbox's IMAP server") from exc
    return connection


def test_imap_connection(hr_integration: HrIntegration) -> None:
    """Connects, logs in, and selects INBOX with the currently-saved config -- then
    disconnects. Raises ImapError on any failure; returns None on success. Used by the
    Settings page's "Test IMAP connection" button, and never touches imap_last_uid or
    fetches any actual mail."""
    connection = _connect(hr_integration)
    try:
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise ImapError("Could not select the INBOX folder")
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _parse_message(raw: bytes) -> dict:
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    from_name, from_address = email.utils.parseaddr(parsed.get("From", ""))
    from_address = from_address.strip().lower()
    to_address = email.utils.parseaddr(parsed.get("To", ""))[1].strip() or None
    subject = parsed.get("Subject")
    message_id = parsed.get("Message-ID")

    received_at: Optional[datetime] = None
    date_header = parsed.get("Date")
    if date_header:
        try:
            received_at = email.utils.parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            received_at = None
        if received_at is not None and received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)

    body_part = parsed.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content().strip() if body_part is not None else None

    return {
        "from_address": from_address,
        "to_address": to_address,
        "subject": subject,
        "body": body,
        "received_at": received_at,
        "message_id": message_id,
        "from_name": (from_name or "").strip() or None,  # Part 22.2: for name / thread matching
        "in_reply_to": parsed.get("In-Reply-To"),
        "references": parsed.get("References"),
    }


def poll_hr_inbox(db: Session, hr_integration: Optional[HrIntegration] = None) -> dict:
    """Fetches every message newer than the last checkpoint (imap_last_uid) -- or, on the
    very first ever poll (no checkpoint yet), the whole current inbox once -- dedupes on
    message_id, tries to match each sender against a real Candidate, and stores one
    HrInboundEmail row per message either way. Raises ImapError on any connection/login
    failure; the scheduled job (app/local_import/scheduler.py) is the one place that
    catches and logs that rather than letting it crash the scheduler thread, same
    treatment as the existing local-import scan's own scheduled job.

    Returns {"fetched": int, "stored": int, "matched": int} -- fetched counts every UID
    the server returned for this poll's search (including ones skipped as already-stored
    duplicates), stored/matched count only the new rows this call actually created.
    """
    hr_integration = hr_integration or get_hr_integration(db)
    connection = _connect(hr_integration)
    fetched = stored = matched = 0
    max_uid_seen = hr_integration.imap_last_uid

    try:
        status, _ = connection.select("INBOX")
        if status != "OK":
            raise ImapError("Could not select the INBOX folder")

        criteria = "ALL" if hr_integration.imap_last_uid is None else f"UID {hr_integration.imap_last_uid + 1}:*"
        status, data = connection.uid("search", None, criteria)
        if status != "OK":
            raise ImapError("IMAP search for new mail failed")
        uids = sorted(int(uid) for uid in data[0].split()) if data and data[0] else []

        for uid in uids:
            fetched += 1
            status, msg_data = connection.uid("fetch", str(uid), "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            parsed = _parse_message(raw)

            if parsed["message_id"] and (
                db.query(HrInboundEmail).filter(HrInboundEmail.message_id == parsed["message_id"]).first()
            ):
                max_uid_seen = uid if max_uid_seen is None else max(max_uid_seen, uid)
                continue

            # Part 22.2: email / extra email -> "First Last" or "Last First" -> reply to our email; never guesses between two
            from app.hr_inbox import matching
            from app.platform.tenancy.context import get_current_tenant

            tenant_ctx = get_current_tenant()
            found = matching.match(db, tenant_ctx.tenant_id, from_address=parsed["from_address"], from_name=parsed.get("from_name"),
                                   subject=parsed["subject"], body=parsed["body"], in_reply_to=parsed.get("in_reply_to"),
                                   references=parsed.get("references")) if tenant_ctx is not None else {"candidate_id": None, "suggestions": []}
            candidate = db.get(Candidate, found["candidate_id"]) if found.get("candidate_id") else None
            matched_application = db.get(Application, found["application_id"]) if found.get("application_id") else None

            row = HrInboundEmail(
                from_address=parsed["from_address"],
                to_address=parsed["to_address"],
                subject=parsed["subject"],
                body=parsed["body"],
                received_at=parsed["received_at"],
                message_id=parsed["message_id"],
                matched_candidate_id=candidate.id if candidate else None,
                matched_application_id=matched_application.id if matched_application else None,
                from_name=parsed.get("from_name"), in_reply_to=parsed.get("in_reply_to"), references_header=parsed.get("references"),
                match_rule=found.get("rule"), match_suggestions_json=[str(x) for x in found.get("suggestions") or []] or None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            stored += 1
            try:  # Part 17.7: what it's about, in one line (never blocks storing the mail)
                from app.hr_inbox.triage import triage
                from app.platform.tenancy.context import get_current_tenant

                if get_current_tenant() is not None:
                    triage(db, get_current_tenant(), row)
            except Exception:  # noqa: BLE001
                pass

            if candidate:
                matched += 1
                log_action(
                    db, "candidate", candidate.id, "inbound_email_received", parsed["from_address"],
                    {"subject": parsed["subject"], "hr_inbound_email_id": str(row.id), "summary": row.summary, "topic": row.topic},
                )

            max_uid_seen = uid if max_uid_seen is None else max(max_uid_seen, uid)
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    if max_uid_seen != hr_integration.imap_last_uid:
        hr_integration.imap_last_uid = max_uid_seen
        db.commit()

    return {"fetched": fetched, "stored": stored, "matched": matched}
