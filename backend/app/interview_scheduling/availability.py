"""interviewer_availability service (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 6) -- CRUD
over `InterviewerAvailability` plus `is_interviewer_busy()`, the `recruitment.negotiation.
busy_source`-dispatched busy-check `app/interview_scheduling/negotiation.py` calls instead
of hardcoding `tracker.interviewer_busy_this_week()`.

**Scope decision**: `weekly_pattern_json`/`exceptions_json` are stored as full JSON (a
future richer-availability UI could use day-of-week time RANGES), but the CURRENT
`internal` busy-check below only reads day-level availability (`weekly_pattern_json[day] is
False`, or a matching `exceptions_json` entry) plus `max_interviews_per_day/week` counts
against real `Interview` rows -- this app's own negotiation flow only ever offers 3 fixed
IST hours for "tomorrow," so a hour-range check would add complexity with no behavioral
payoff yet. `calendar` gracefully degrades to the same `internal` check whenever an
interviewer has no linked Employee/User/Google connection to actually query -- never a
hard failure that would block the negotiation flow."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.interview import Interview
from app.models.interviewer_availability import InterviewerAvailability
from app.platform.tenancy.context import TenantContext

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def get_availability_for_email(db: Session, tenant: TenantContext, email: str) -> Optional[InterviewerAvailability]:
    return (
        db.query(InterviewerAvailability)
        .filter(InterviewerAvailability.tenant_id == tenant.tenant_id, InterviewerAvailability.interviewer_email == email.strip().lower())
        .first()
    )


def upsert_availability(
    db: Session, tenant: TenantContext, *, interviewer_email: str, interviewer_name: Optional[str] = None,
    employee_id: Optional[UUID] = None, weekly_pattern: Optional[dict] = None, exceptions: Optional[list] = None,
    max_interviews_per_day: Optional[int] = None, max_interviews_per_week: Optional[int] = None,
    skills: Optional[list] = None, source: str = "manual",
) -> InterviewerAvailability:
    email_key = interviewer_email.strip().lower()
    row = get_availability_for_email(db, tenant, email_key)
    if row is None:
        row = InterviewerAvailability(tenant_id=tenant.tenant_id, interviewer_email=email_key)
        db.add(row)
    row.interviewer_name = interviewer_name or row.interviewer_name
    row.employee_id = employee_id if employee_id is not None else row.employee_id
    if weekly_pattern is not None:
        row.weekly_pattern_json = weekly_pattern
    if exceptions is not None:
        row.exceptions_json = exceptions
    if max_interviews_per_day is not None:
        row.max_interviews_per_day = max_interviews_per_day
    if max_interviews_per_week is not None:
        row.max_interviews_per_week = max_interviews_per_week
    if skills is not None:
        row.skills_json = skills
    row.source = source
    db.commit()
    db.refresh(row)
    return row


def list_availability(db: Session, tenant: TenantContext) -> list[InterviewerAvailability]:
    return db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id).order_by(InterviewerAvailability.interviewer_name).all()


def _week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _count_interviews_on_day(db: Session, tenant: TenantContext, email: str, day: date) -> int:
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(Interview)
        .filter(Interview.tenant_id == tenant.tenant_id, Interview.interviewer_email == email, Interview.scheduled_at >= day_start, Interview.scheduled_at < day_end)
        .count()
    )


def _count_interviews_in_week(db: Session, tenant: TenantContext, email: str, day: date) -> int:
    week_start, week_end = _week_bounds(day)
    start = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(week_end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    return (
        db.query(Interview)
        .filter(Interview.tenant_id == tenant.tenant_id, Interview.interviewer_email == email, Interview.scheduled_at >= start, Interview.scheduled_at < end)
        .count()
    )


def _hours(day_pattern) -> Optional[list[tuple[str, str]]]:
    """weekly_pattern_json[day]: False = off, a list of {"start","end"} (company time,
    "HH:MM") = working hours, anything else = available all day (None)."""
    if day_pattern is False:
        return []
    if isinstance(day_pattern, list):
        out = []
        for r in day_pattern:
            if isinstance(r, dict) and r.get("start") and r.get("end"):
                out.append((str(r["start"])[:5], str(r["end"])[:5]))
        return out
    return None


def _company_tz(db: Session, tenant: TenantContext):
    from zoneinfo import ZoneInfo

    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        return ZoneInfo(SettingsService(db).get("org.timezone", SettingContext(tenant=tenant)) or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Kolkata")


def _slot_free(db: Session, tenant: TenantContext, row, email: str, slot: datetime, tz) -> bool:
    local = slot.astimezone(tz)
    hours = _hours((row.weekly_pattern_json or {}).get(_WEEKDAY_KEYS[local.weekday()]) if isinstance(row.weekly_pattern_json, dict) else None)
    if hours is not None:
        hhmm = local.strftime("%H:%M")
        if not any(start <= hhmm < end for start, end in hours):
            return False
    # an interview already booked in the app within an hour of this slot -> not free
    clash = (db.query(Interview.id).filter(Interview.tenant_id == tenant.tenant_id, Interview.interviewer_email == email,
                                          Interview.scheduled_at > slot - timedelta(minutes=59), Interview.scheduled_at < slot + timedelta(minutes=59))
             .first())
    return clash is None


def _is_busy_internal(db: Session, tenant: TenantContext, email: str, day: date, slot_times: Optional[list[datetime]] = None) -> bool:
    """Part 17.12: the app is the only source. Busy when: that weekday is off, the date is
    blocked, the daily/weekly limit is reached, or NONE of the offered slot times fits their
    working hours without clashing with an interview already booked in the app. No
    availability row yet -> only booked interviews count (permissive)."""
    row = get_availability_for_email(db, tenant, email)
    tz = _company_tz(db, tenant)
    if row is not None:
        weekday_key = _WEEKDAY_KEYS[day.weekday()]
        if isinstance(row.weekly_pattern_json, dict) and row.weekly_pattern_json.get(weekday_key) is False:
            return True
        for exception in row.exceptions_json or []:
            if exception.get("date") == day.isoformat():
                if not exception.get("available", False):
                    return True
        if row.max_interviews_per_day and _count_interviews_on_day(db, tenant, email, day) >= row.max_interviews_per_day:
            return True
        if row.max_interviews_per_week and _count_interviews_in_week(db, tenant, email, day) >= row.max_interviews_per_week:
            return True
    if slot_times:
        class _Open:  # no row: every hour counts as working time
            weekly_pattern_json: dict = {}
        return not any(_slot_free(db, tenant, row or _Open(), email, s, tz) for s in slot_times)
    return False


def free_slots(db: Session, tenant: TenantContext, email: str, slot_times: list[datetime]) -> list[datetime]:
    """Which of these slot times this interviewer can take (used by the HR availability view)."""
    row = get_availability_for_email(db, tenant, email)
    tz = _company_tz(db, tenant)
    out = []
    for s in slot_times:
        if _is_busy_internal(db, tenant, email, s.astimezone(tz).date(), None):
            continue

        class _Open:
            weekly_pattern_json: dict = {}
        if _slot_free(db, tenant, row or _Open(), email, s, tz):
            out.append(s)
    return out


def _is_busy_calendar(db: Session, tenant: TenantContext, email: str, day: date, slot_times: list[datetime]) -> bool:
    from app.core.crypto import decrypt
    from app.integrations.google_calendar import DEFAULT_INTERVIEW_DURATION_MINUTES, check_calendar_availability
    from app.models.core_hr import Employee
    from app.models.user_integration import UserIntegration

    row = get_availability_for_email(db, tenant, email)
    if row is None or not row.employee_id:
        return _is_busy_internal(db, tenant, email, day, slot_times)
    employee = db.get(Employee, row.employee_id)
    if employee is None or not employee.user_id:
        return _is_busy_internal(db, tenant, email, day, slot_times)
    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == employee.user_id, UserIntegration.provider == "google")
        .first()
    )
    if integration is None or not integration.refresh_token:
        return _is_busy_internal(db, tenant, email, day, slot_times)

    window_start = min(slot_times)
    window_end = max(slot_times) + timedelta(minutes=DEFAULT_INTERVIEW_DURATION_MINUTES)
    try:
        available = check_calendar_availability(decrypt(integration.refresh_token), window_start, window_end)
    except Exception:
        return _is_busy_internal(db, tenant, email, day, slot_times)
    # the calendar being free isn't enough: the app's own hours / limits / bookings apply too
    return (not available) or _is_busy_internal(db, tenant, email, day, slot_times)


def is_interviewer_busy(
    db: Session, tenant: TenantContext, *, busy_source: str, tracker_path: str, interviewer_name: str,
    interviewer_email: Optional[str], day: date, slot_times: list[datetime],
) -> bool:
    """Part 17.12: never reads Excel. "calendar" also asks the person's connected calendar;
    anything else (incl. an old "excel" value) is the app's own check. No email -> busy
    (nobody can be emailed an offer without one)."""
    if not interviewer_email:
        return True
    if busy_source == "calendar":
        return _is_busy_calendar(db, tenant, interviewer_email, day, slot_times)
    return _is_busy_internal(db, tenant, interviewer_email, day, slot_times)
