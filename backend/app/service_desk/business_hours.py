"""Business-hours arithmetic for SLA timers (docs/HRMS_COMPLETE_SPEC.txt Part 11 section A:
"business hours by location calendar"). Pure functions over a BusinessCalendar-shaped
object, so they're testable without a DB. All inputs/outputs are timezone-aware UTC; the
calendar's own timezone decides what "09:00-18:00 Mon-Fri" means."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_MAX_DAYS_SCANNED = 3660  # ~10 years -- a calendar with no working days can't loop forever


@dataclass
class Hours:
    timezone: str
    working_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    start_time: str = "09:00"
    end_time: str = "18:00"
    holidays: set = field(default_factory=set)

    @classmethod
    def from_calendar(cls, calendar) -> "Hours":
        return cls(
            timezone=calendar.timezone, working_days=list(calendar.working_days or []), start_time=calendar.start_time,
            end_time=calendar.end_time, holidays={date.fromisoformat(d) for d in (calendar.holidays_json or [])},
        )


def _t(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _window(hours: Hours, day: date) -> tuple[datetime, datetime] | None:
    if day.weekday() not in hours.working_days or day in hours.holidays:
        return None
    tz = ZoneInfo(hours.timezone)
    start = datetime.combine(day, _t(hours.start_time), tzinfo=tz)
    end = datetime.combine(day, _t(hours.end_time), tzinfo=tz)
    return (start, end) if end > start else None


def add_business_minutes(start: datetime, minutes: int, hours: Hours) -> datetime:
    """The UTC instant `minutes` business minutes after `start`."""
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if not hours.working_days:
        raise ValueError("calendar has no working days")
    tz = ZoneInfo(hours.timezone)
    cursor = start.astimezone(tz)
    remaining = timedelta(minutes=minutes)
    day = cursor.date()
    for _ in range(_MAX_DAYS_SCANNED):
        window = _window(hours, day)
        if window is not None:
            begin = max(cursor, window[0])
            if begin < window[1]:
                available = window[1] - begin
                if remaining <= available:
                    return (begin + remaining).astimezone(timezone.utc)
                remaining -= available
        day += timedelta(days=1)
        cursor = datetime.combine(day, time(0, 0), tzinfo=tz)
    raise ValueError("could not fit the SLA inside the calendar")


def business_minutes_between(a: datetime, b: datetime, hours: Hours) -> int:
    """Business minutes elapsed in [a, b); 0 if b <= a."""
    if b <= a:
        return 0
    tz = ZoneInfo(hours.timezone)
    a_local, b_local = a.astimezone(tz), b.astimezone(tz)
    total = timedelta()
    day = a_local.date()
    while day <= b_local.date():
        window = _window(hours, day)
        if window is not None:
            begin, end = max(a_local, window[0]), min(b_local, window[1])
            if end > begin:
                total += end - begin
        day += timedelta(days=1)
    return int(total.total_seconds() // 60)
