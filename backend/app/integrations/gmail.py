import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import settings
from app.integrations.google_calendar import SCOPES, TOKEN_URI


class GmailError(Exception):
    """Raised when sending an email via the Gmail API fails."""


def send_email(refresh_token: str, *, to: str, subject: str, body: str) -> str:
    """Send as the connected user via the Gmail API. Returns the sent message id.

    Reuses the same "google" provider connection as Calendar (see google_calendar.py) --
    a refresh token obtained before gmail.send was added to SCOPES will fail here with an
    insufficient-scope error until the user reconnects.
    """
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        service = build("gmail", "v1", credentials=credentials)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as exc:
        raise GmailError(f"Failed to send email via Gmail: {exc}") from exc
    return sent.get("id")
