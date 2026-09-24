"""imap provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- a generic, tenant-owned
IMAP connection. poll() logic mirrors app/integrations/imap_poll.py's own fetch/parse
(this app's current IMAP behavior) genericized off config_json/secret_ref instead of the
singleton HrIntegration row; does not persist a checkpoint itself (imap_last_uid) --
that's the caller's (Part 4's inbound router) job once it exists, same as the poll's
`since` cursor.
"""

import email
import email.policy
import email.utils
import imaplib
from datetime import datetime, timezone
from typing import Optional

from app.platform.connectors.capabilities import InboundEmail, ProviderResult

PROVIDER_CODE = "imap"
CAPABILITIES = ("EmailReceiver",)
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["host", "port", "username"],
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer", "default": 993},
        "username": {"type": "string"},
        "mailbox": {"type": "string", "default": "INBOX"},
    },
}
SECRET_FIELDS = ("password",)
IMAP_TIMEOUT_SECONDS = 15


class ImapAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.password = secrets.get("password", "")

    def _connect(self) -> imaplib.IMAP4:
        client = imaplib.IMAP4_SSL(self.config["host"], self.config.get("port", 993), timeout=IMAP_TIMEOUT_SECONDS)
        client.login(self.config["username"], self.password)
        client.select(self.config.get("mailbox", "INBOX"))
        return client

    def poll(self, since: Optional[datetime]) -> list[InboundEmail]:
        client = self._connect()
        try:
            criteria = "ALL"
            if since is not None:
                criteria = f'(SINCE "{since.strftime("%d-%b-%Y")}")'
            status, data = client.search(None, criteria)
            if status != "OK":
                return []
            results: list[InboundEmail] = []
            for uid in data[0].split():
                status, msg_data = client.fetch(uid, "(RFC822)")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                parsed = email.message_from_bytes(raw, policy=email.policy.default)
                received_at = None
                date_header = parsed.get("Date")
                if date_header:
                    parsed_date = email.utils.parsedate_to_datetime(date_header)
                    if parsed_date is not None:
                        received_at = parsed_date if parsed_date.tzinfo else parsed_date.replace(tzinfo=timezone.utc)
                body = ""
                if parsed.get_body(preferencelist=("plain",)):
                    body = parsed.get_body(preferencelist=("plain",)).get_content()
                results.append(InboundEmail(
                    from_address=str(parsed.get("From", "")),
                    to_address=str(parsed.get("To", "")),
                    subject=str(parsed.get("Subject", "")),
                    body_text=body,
                    message_id=str(parsed.get("Message-ID", "")),
                    in_reply_to=str(parsed.get("In-Reply-To", "")) or None,
                    received_at=received_at,
                ))
            return results
        finally:
            try:
                client.close()
            except imaplib.IMAP4.error:
                pass
            client.logout()

    def test_connection(self) -> ProviderResult:
        try:
            client = self._connect()
            client.logout()
            return ProviderResult(success=True)
        except (imaplib.IMAP4.error, OSError) as exc:
            return ProviderResult(success=False, error=str(exc) or "IMAP connection failed")

    def health_check(self) -> ProviderResult:
        return self.test_connection()
