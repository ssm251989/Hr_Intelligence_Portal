"""Generates the .ics (RFC 5545 VCALENDAR/VEVENT) calendar invite attached to a confirmed
interview's email notifications (see app/interview_scheduling/negotiation.py _finalize) --
the portable, no-OAuth-required replacement for that flow's old dependency on the Google
Calendar API (app/integrations/google_calendar.create_calendar_event via
app/interview_scheduling/confirmation.create_confirmed_calendar_event), which needs a live,
per-interviewer refresh token and has already been seen to fail on an expired/revoked one in
real use. Uses the `icalendar` package rather than hand-rolling the format.
"""

import uuid
from datetime import datetime, timedelta, timezone

from icalendar import Calendar, Event, vCalAddress, vText


def build_interview_ics(
    *,
    start: datetime,
    duration_minutes: int,
    summary: str,
    organizer_email: str,
    attendee_emails: list[str],
    description: str = "",
    prodid_org: str = "HR Automation",
    location: str = "",
) -> bytes:
    """Returns one complete VCALENDAR payload (bytes, RFC 5545's required CRLF line
    endings -- pass through unchanged, never re-encoded via a str content manager, which
    would normalize them to bare LF) for a single interview event. `start` is converted to
    UTC so the event never needs its own VTIMEZONE component."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start_utc = start.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=duration_minutes)

    organizer_domain = organizer_email.rsplit("@", 1)[-1] if "@" in organizer_email else "invalid"

    event = Event()
    event.add("uid", f"{uuid.uuid4()}@{organizer_domain}")
    event.add("summary", summary)
    event.add("description", description)
    if location:  # fix 2026-10-04: the meeting link, so calendars show a "Join" link
        event.add("location", location)
        if location.startswith("http"):
            event.add("url", location)
    event.add("dtstart", start_utc)
    event.add("dtend", end_utc)
    event.add("dtstamp", datetime.now(timezone.utc))

    organizer = vCalAddress(f"MAILTO:{organizer_email}")
    organizer.params["cn"] = vText(organizer_email)
    event["organizer"] = organizer

    for email in attendee_emails:
        attendee = vCalAddress(f"MAILTO:{email}")
        attendee.params["cn"] = vText(email)
        attendee.params["role"] = vText("REQ-PARTICIPANT")
        event.add("attendee", attendee, encode=0)

    calendar = Calendar()
    calendar.add("prodid", f"-//{prodid_org}//Interview Scheduling//EN")
    calendar.add("version", "2.0")
    # REQUEST (not PUBLISH) is what makes Outlook/Gmail/Apple Mail offer an "Accept/
    # Decline/Add to calendar" action on the attachment rather than treating it as an
    # inert file.
    calendar.add("method", "REQUEST")
    calendar.add_component(event)

    return calendar.to_ical()
