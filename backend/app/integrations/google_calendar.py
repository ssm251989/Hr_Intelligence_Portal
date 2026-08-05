from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
# Interviews default to a 1-hour slot when the caller doesn't specify one.
DEFAULT_INTERVIEW_DURATION_MINUTES = 60


class GoogleCalendarError(Exception):
    """Raised when talking to Google's OAuth or Calendar APIs fails."""


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def build_authorization_url(state: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def exchange_code_for_refresh_token(code: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to exchange authorization code: {exc}") from exc

    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise GoogleCalendarError(
            "Google did not return a refresh token. The user likely already granted "
            "access previously -- ask them to revoke it at "
            "https://myaccount.google.com/permissions and reconnect."
        )
    return refresh_token


def create_calendar_event(
    refresh_token: str,
    *,
    summary: str,
    description: str,
    start: datetime,
    attendee_emails: list[str],
    duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
) -> dict:
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=duration_minutes)).isoformat()},
        "attendees": [{"email": email} for email in attendee_emails],
    }
    try:
        service = build("calendar", "v3", credentials=credentials)
        event = service.events().insert(calendarId="primary", body=body).execute()
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to create calendar event: {exc}") from exc

    return {"event_id": event.get("id"), "html_link": event.get("htmlLink")}
