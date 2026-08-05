from datetime import datetime, timezone

from app.integrations.google_calendar import create_calendar_event


class _FakeEvents:
    def __init__(self, captured):
        self._captured = captured

    def insert(self, calendarId, body):
        self._captured["calendarId"] = calendarId
        self._captured["body"] = body
        return self

    def execute(self):
        return {"id": "evt_123", "htmlLink": "https://calendar.google.com/event?eid=evt_123"}


class _FakeService:
    def __init__(self, captured):
        self._captured = captured

    def events(self):
        return _FakeEvents(self._captured)


def _patch_build(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.integrations.google_calendar.build", lambda *args, **kwargs: _FakeService(captured)
    )
    return captured


def test_create_calendar_event_sends_ist_datetime_and_explicit_timezone(monkeypatch):
    captured = _patch_build(monkeypatch)

    # 06:50 UTC is 12:20 IST (UTC+5:30) -- this is what a correctly-converted "12:20 PM
    # India time" request looks like by the time it reaches the calendar client.
    start = datetime(2026, 8, 10, 6, 50, tzinfo=timezone.utc)

    result = create_calendar_event(
        "fake-refresh-token",
        summary="Interview: Test Candidate — Test Role",
        description="desc",
        start=start,
        attendee_emails=["candidate@example.com", "interviewer@example.com"],
    )

    body = captured["body"]
    assert body["start"] == {"dateTime": "2026-08-10T12:20:00+05:30", "timeZone": "Asia/Kolkata"}
    assert body["end"] == {"dateTime": "2026-08-10T13:20:00+05:30", "timeZone": "Asia/Kolkata"}
    assert result == {"event_id": "evt_123", "html_link": "https://calendar.google.com/event?eid=evt_123"}


def test_create_calendar_event_treats_naive_start_as_utc_not_local_server_time(monkeypatch):
    captured = _patch_build(monkeypatch)

    # No tzinfo at all -- must not be silently treated as local server time (which would
    # make the resulting IST conversion depend on whatever timezone the process runs in).
    start = datetime(2026, 8, 10, 6, 50)

    create_calendar_event(
        "fake-refresh-token", summary="Interview", description="desc", start=start, attendee_emails=[]
    )

    assert captured["body"]["start"]["dateTime"] == "2026-08-10T12:20:00+05:30"


def test_create_calendar_event_respects_custom_duration(monkeypatch):
    captured = _patch_build(monkeypatch)
    start = datetime(2026, 8, 10, 6, 50, tzinfo=timezone.utc)

    create_calendar_event(
        "fake-refresh-token",
        summary="Interview",
        description="desc",
        start=start,
        attendee_emails=[],
        duration_minutes=30,
    )

    assert captured["body"]["end"]["dateTime"] == "2026-08-10T12:50:00+05:30"
