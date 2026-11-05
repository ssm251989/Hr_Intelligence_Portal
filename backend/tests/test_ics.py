"""app/integrations/ics.py's build_interview_ics -- the .ics generation step the pick-2-of-3
negotiation mechanic's confirmation step (app/interview_scheduling/negotiation.py _finalize)
attaches to both parties' confirmation emails instead of creating a Google Calendar event."""

from datetime import datetime, timezone

from icalendar import Calendar

from app.integrations.ics import build_interview_ics


def _parse_event(payload: bytes):
    calendar = Calendar.from_ical(payload)
    events = list(calendar.walk("VEVENT"))
    assert len(events) == 1
    return events[0]


def test_build_interview_ics_encodes_start_time_and_duration():
    start = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
    payload = build_interview_ics(
        start=start, duration_minutes=60, summary="Interview: Jane Doe — Backend Engineer",
        organizer_email="hr@example.com", attendee_emails=["interviewer@example.com", "jane@example.com"],
    )
    event = _parse_event(payload)
    assert event["dtstart"].dt == start
    assert event["dtend"].dt == datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)


def test_build_interview_ics_encodes_summary_and_attendees():
    payload = build_interview_ics(
        start=datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc), duration_minutes=60,
        summary="Interview: Jane Doe — Backend Engineer", organizer_email="hr@example.com",
        attendee_emails=["interviewer@example.com", "jane@example.com"],
        description="Interview confirmed for application abc-123.",
    )
    event = _parse_event(payload)
    assert str(event["summary"]) == "Interview: Jane Doe — Backend Engineer"
    assert str(event["description"]) == "Interview confirmed for application abc-123."
    assert str(event["organizer"]) == "MAILTO:hr@example.com"

    attendees = event.get("attendee")
    attendees = attendees if isinstance(attendees, list) else [attendees]
    assert {str(a) for a in attendees} == {"MAILTO:interviewer@example.com", "MAILTO:jane@example.com"}


def test_build_interview_ics_treats_a_naive_start_as_utc():
    naive_start = datetime(2026, 8, 25, 15, 0)
    payload = build_interview_ics(
        start=naive_start, duration_minutes=30, summary="Interview", organizer_email="hr@example.com",
        attendee_emails=["a@example.com"],
    )
    event = _parse_event(payload)
    assert event["dtstart"].dt == datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


def test_build_interview_ics_uses_request_method_so_calendar_clients_offer_accept_decline():
    payload = build_interview_ics(
        start=datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc), duration_minutes=60,
        summary="Interview", organizer_email="hr@example.com", attendee_emails=["a@example.com"],
    )
    calendar = Calendar.from_ical(payload)
    assert str(calendar.get("method")) == "REQUEST"


def test_build_interview_ics_preserves_required_crlf_line_endings():
    payload = build_interview_ics(
        start=datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc), duration_minutes=60,
        summary="Interview", organizer_email="hr@example.com", attendee_emails=["a@example.com"],
    )
    assert b"BEGIN:VCALENDAR\r\n" in payload
    assert b"\n" in payload  # sanity: the payload isn't empty/single-line
    assert payload.count(b"\r\n") == payload.count(b"\n")  # every LF is part of a CRLF pair
