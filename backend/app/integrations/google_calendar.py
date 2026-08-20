import secrets
import string
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import settings

# gmail.send was added alongside calendar.events so a single Google connection covers
# both interview scheduling and new-application email notifications. This does NOT
# retroactively grant gmail.send to refresh tokens obtained before this change -- Google
# scopes are fixed at consent time, so any already-connected user must reconnect
# (POST /integrations/google/connect again) to pick up the new scope. There is
# deliberately no attempt to silently "upgrade" an old token; a stale connection just
# keeps working for Calendar and fails gmail.send calls until the user reconnects.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
# Interviews default to a 1-hour slot when the caller doesn't specify one.
DEFAULT_INTERVIEW_DURATION_MINUTES = 60
# PKCE (RFC 7636) code_verifier charset and length.
_CODE_VERIFIER_CHARS = string.ascii_letters + string.digits + "-._~"
# This app only operates in India -- Calendar events are always created in IST.
APP_TIMEZONE = ZoneInfo("Asia/Kolkata")


def format_ist_datetime(dt: datetime) -> str:
    """The one slot-time format used everywhere a candidate or recruiter reads one: the
    proposal email's slot links, the confirmation page, and the tracker's Interview Log
    "Candidate Preferred Time"/"Final Scheduled Time" columns (see
    app/interview_scheduling/confirmation.py and service.py). Previously each of those
    three places formatted independently (and the tracker columns used a bare UTC ISO
    string), which is how "26 Aug 2026" and a weekday-only rendering could drift out of
    sync -- one shared function, always normalizing through IST via .astimezone regardless
    of the input's own tzinfo, so a date is never displayed (or matched against, in
    update_interview_log_row) without its actual date.
    """
    return dt.astimezone(APP_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")


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


def generate_code_verifier() -> str:
    """A random PKCE code_verifier, generated up front so it can be embedded in `state`

    and survive the round trip to Google and back to /callback -- /connect and /callback
    are separate HTTP requests, so a verifier held only on a local Flow object is lost.
    """
    return "".join(secrets.choice(_CODE_VERIFIER_CHARS) for _ in range(128))


def build_authorization_url(state: str, code_verifier: str) -> str:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def exchange_code_for_refresh_token(code: str, code_verifier: str) -> str:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
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

    # `start` should always arrive timezone-aware (the API only ever passes values parsed
    # from an ISO string with an explicit offset/Z) -- but treat a naive value as UTC
    # rather than relying on Python's default of silently assuming local server time.
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=duration_minutes)

    # Google resolves an offset-qualified dateTime to the correct absolute instant either
    # way, but pairing dateTime with an explicit IANA timeZone (rather than a bare
    # timestamp) is what Google's own API docs show and avoids it ever defaulting to UTC.
    start_ist = start.astimezone(APP_TIMEZONE)
    end_ist = end.astimezone(APP_TIMEZONE)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_ist.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_ist.isoformat(), "timeZone": "Asia/Kolkata"},
        "attendees": [{"email": email} for email in attendee_emails],
    }
    try:
        service = build("calendar", "v3", credentials=credentials)
        event = service.events().insert(calendarId="primary", body=body).execute()
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to create calendar event: {exc}") from exc

    return {"event_id": event.get("id"), "html_link": event.get("htmlLink")}


def check_calendar_availability(refresh_token: str, start: datetime, end: datetime) -> bool:
    """True if the interviewer's own primary calendar has no events overlapping [start,
    end), False if it does. Uses the freeBusy API rather than listing events -- it answers
    exactly this yes/no question without the caller needing to interpret event details it
    has no business reading (e.g. Interview Scheduling automation checking availability
    for someone else's calendar, see app/interview_scheduling/service.py).
    """
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    body = {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": "primary"}]}
    try:
        service = build("calendar", "v3", credentials=credentials)
        result = service.freebusy().query(body=body).execute()
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to check calendar availability: {exc}") from exc

    busy_periods = result.get("calendars", {}).get("primary", {}).get("busy", [])
    return len(busy_periods) == 0
