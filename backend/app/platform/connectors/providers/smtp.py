"""smtp provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- a generic, tenant-owned
SMTP connection. Logic mirrors app/integrations/hr_email.py's send_hr_email (this app's
own current SMTP behavior) exactly, just reading from a connection's config_json/secret_ref
instead of the singleton HrIntegration row.
"""

import smtplib
from email.message import EmailMessage

from app.platform.connectors.capabilities import OutboundEmail, ProviderResult

PROVIDER_CODE = "smtp"
CAPABILITIES = ("EmailSender",)
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["host", "port", "username"],
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer", "default": 587},
        "username": {"type": "string"},
        "use_tls": {"type": "boolean", "default": True},
        "from_address": {"type": "string"},
    },
}
SECRET_FIELDS = ("password",)
SMTP_TIMEOUT_SECONDS = 15


class SmtpAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.password = secrets.get("password", "")

    def _client(self) -> smtplib.SMTP:
        client = smtplib.SMTP(self.config["host"], self.config.get("port", 587), timeout=SMTP_TIMEOUT_SECONDS)
        if self.config.get("use_tls", True):
            client.starttls()
        client.login(self.config["username"], self.password)
        return client

    def send(self, msg: OutboundEmail) -> ProviderResult:
        message = EmailMessage()
        message["Subject"] = msg.subject
        message["From"] = self.config.get("from_address") or self.config["username"]
        message["To"] = ", ".join(msg.to)
        if msg.cc:
            message["Cc"] = ", ".join(msg.cc)
        if msg.reply_to:
            message["Reply-To"] = msg.reply_to
        message.set_content(msg.body_text)
        if msg.body_html:
            message.add_alternative(msg.body_html, subtype="html")
        for att in msg.attachments or []:
            message.add_attachment(att["content"], maintype=att["maintype"], subtype=att["subtype"], filename=att["filename"])

        recipients = list(msg.to) + list(msg.cc or []) + list(msg.bcc or [])
        try:
            with self._client() as client:
                client.send_message(message, to_addrs=recipients)
            return ProviderResult(success=True)
        except (smtplib.SMTPException, OSError) as exc:
            return ProviderResult(success=False, error=str(exc) or "SMTP send failed")

    def test_connection(self) -> ProviderResult:
        try:
            with self._client():
                pass
            return ProviderResult(success=True)
        except (smtplib.SMTPException, OSError) as exc:
            return ProviderResult(success=False, error=str(exc) or "SMTP connection failed")

    def health_check(self) -> ProviderResult:
        return self.test_connection()
