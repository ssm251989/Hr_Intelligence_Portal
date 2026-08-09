"""Monthly time-series + comparison-month math behind the jobs dashboard stat cards.

Kept separate from app/reports/router.py so the month-bucketing and percentage-change
logic can be reasoned about (and tested) independently of the FastAPI/session wiring.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.schemas.reports import MonthlyPoint, StatTrend

# This app is India-only (see frontend istLocalInputToUtcIso) -- every "current month" /
# "last month" boundary below is anchored to IST's calendar, not UTC's. Naively using
# `some_utc_datetime.month` is wrong for the ~5.5 hour window at the start of every
# calendar month (IST = UTC+5:30): during that window IST has already rolled into the
# new month while UTC's date is still the last day of the previous one, which silently
# makes "current month" -- and therefore "last month" -- one month behind for anyone
# using the app during that window.
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_month_boundary(year: int, month: int) -> datetime:
    """The UTC instant of 00:00 IST on the 1st of `year`-`month`."""
    return datetime(year, month, 1, tzinfo=timezone.utc) - _IST_OFFSET


def month_start(dt: datetime) -> datetime:
    """The month-start boundary for the IST calendar month that instant `dt` falls into."""
    ist = dt + _IST_OFFSET
    return _ist_month_boundary(ist.year, ist.month)


def shift_months(ms: datetime, delta: int) -> datetime:
    """Shift a month-start boundary (as returned by month_start) by whole calendar months."""
    ist = ms + _IST_OFFSET  # recover the (year, month) the boundary represents
    total = ist.year * 12 + (ist.month - 1) + delta
    year, month = divmod(total, 12)
    return _ist_month_boundary(year, month + 1)


def month_key(ms: datetime) -> str:
    ist = ms + _IST_OFFSET
    return f"{ist.year:04d}-{ist.month:02d}"


def last_12_month_starts(now: datetime) -> list[datetime]:
    """12 month-starts, oldest first, ending with the current (in-progress) month."""
    current = month_start(now)
    return [shift_months(current, -i) for i in range(11, -1, -1)]


def comparable_month_starts(now: datetime) -> list[datetime]:
    """The 12 *completed* months a "compare to" dropdown may target: last month back
    through 12 months ago. Deliberately excludes the current month -- it isn't over yet."""
    current = month_start(now)
    return [shift_months(current, -i) for i in range(1, 13)]


def parse_compare_month(value: Optional[str], now: datetime) -> datetime:
    """Resolve the compare_month query param to a month-start, defaulting to last month.

    Raises ValueError (caller maps this to HTTP 400) if the value isn't a real "YYYY-MM"
    month, or isn't one of the past 12 completed months the dropdown actually offers.
    """
    candidates = comparable_month_starts(now)
    if value is None:
        return candidates[0]
    try:
        year_str, month_str = value.split("-")
        candidate = _ist_month_boundary(int(year_str), int(month_str))
    except (ValueError, TypeError):
        raise ValueError(f"compare_month must be in YYYY-MM format, got {value!r}")
    if candidate not in candidates:
        raise ValueError("compare_month must be one of the past 12 completed months")
    return candidate


def _completions_in_window(db: Session, start: datetime, end: datetime):
    return (
        db.query(AuditLog.entity_id, AuditLog.created_at)
        .filter(
            AuditLog.entity_type == "application",
            AuditLog.action == "onboarding_completed",
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        )
        .all()
    )


def hires_and_avg_time_to_hire(db: Session, start: datetime, end: datetime) -> tuple[int, Optional[float]]:
    """Hires completed, and their average time-to-hire in days, within [start, end)."""
    rows = _completions_in_window(db, start, end)
    if not rows:
        return 0, None
    app_ids = [row.entity_id for row in rows]
    created_at_by_id = dict(
        db.query(Application.id, Application.created_at).filter(Application.id.in_(app_ids)).all()
    )
    deltas = [
        (completed_at - created_at_by_id[entity_id]).total_seconds() / 86400
        for entity_id, completed_at in rows
        if entity_id in created_at_by_id
    ]
    avg = round(sum(deltas) / len(deltas), 1) if deltas else None
    return len(rows), avg


def cumulative_count_as_of(db: Session, model, cutoff: datetime) -> int:
    """Count of `model` rows created before `cutoff` -- a running total as of a month-end."""
    return db.query(func.count(model.id)).filter(model.created_at < cutoff).scalar() or 0


def published_snapshot_as_of(db: Session, cutoff: datetime) -> tuple[int, int]:
    """Approximated (active_jobs, open_positions) "as of" a given month-end.

    This is NOT a real historical snapshot -- job status isn't versioned, so there's no
    way to know what a job's status actually was in a past month. It approximates by
    taking jobs *created* by that cutoff and checking their *current* status/positions,
    which silently mis-attributes any job whose status has since changed (published
    later, or closed since). Only valid as a rough trend line, never presented as exact.
    """
    active = (
        db.query(func.count(JobRole.id))
        .filter(JobRole.created_at < cutoff, JobRole.status == "published")
        .scalar()
        or 0
    )
    open_positions = (
        db.query(func.coalesce(func.sum(JobRole.positions_count), 0))
        .filter(JobRole.created_at < cutoff, JobRole.status == "published")
        .scalar()
        or 0
    )
    return int(active), int(open_positions)


def pct_change(current: Optional[float], compare: Optional[float]) -> Optional[float]:
    if current is None or compare is None:
        return None
    if compare == 0:
        return 0.0 if current == 0 else None  # undefined ("infinite") -- surfaced as "--" by the UI
    return round((current - compare) / compare * 100, 1)


JOB_STATUS_OVERVIEW_PERIODS = ("this_month", "last_3_months", "this_year", "all_time")


def job_status_period_start(period: str, now: datetime) -> Optional[datetime]:
    """Start of the requested period as an IST-anchored UTC instant, or None for "all_time"
    (no lower bound). Raises ValueError for anything outside JOB_STATUS_OVERVIEW_PERIODS.
    """
    if period == "all_time":
        return None
    if period == "this_month":
        return month_start(now)
    if period == "last_3_months":
        # A rolling 3-calendar-month window that includes the current (in-progress) month.
        return shift_months(month_start(now), -2)
    if period == "this_year":
        ist = now + _IST_OFFSET
        return _ist_month_boundary(ist.year, 1)
    raise ValueError(f"period must be one of {JOB_STATUS_OVERVIEW_PERIODS}, got {period!r}")


def build_trend(
    month_starts: Sequence[datetime],
    values: Sequence[Optional[float]],
    compare_month_start: datetime,
    compare_value: Optional[float],
    current_value: Optional[float],
    is_approximate: bool = False,
) -> StatTrend:
    series = [MonthlyPoint(month=month_key(ms), value=value) for ms, value in zip(month_starts, values)]
    return StatTrend(
        series=series,
        compare_month=month_key(compare_month_start),
        compare_value=compare_value,
        pct_change=pct_change(current_value, compare_value),
        is_approximate=is_approximate,
    )


def job_application_count_and_trend(
    db: Session, job_id: uuid.UUID, now: datetime
) -> tuple[int, Optional[float]]:
    """Total applications for one job, and its % change vs. that same cumulative count as
    of last month-end -- the per-job version of the dashboard's Total Applications trend,
    scoped to a single job_role_id instead of every job.
    """
    current = db.query(func.count(Application.id)).filter(Application.job_role_id == job_id).scalar() or 0
    last_month_end = month_start(now)
    compare = (
        db.query(func.count(Application.id))
        .filter(Application.job_role_id == job_id, Application.created_at < last_month_end)
        .scalar()
        or 0
    )
    return current, pct_change(current, compare)


def job_avg_time_to_hire(db: Session, job_id: uuid.UUID) -> Optional[float]:
    """All-time average time-to-hire for one job's completed hires (None if it has none
    yet). Same calculation as hires_and_avg_time_to_hire (audit_log's onboarding_completed
    timestamp minus the application's created_at), but scoped to a single job_role_id and
    not windowed to a calendar month -- a job's own hiring history doesn't reset monthly.
    """
    rows = (
        db.query(AuditLog.entity_id, AuditLog.created_at)
        .join(Application, Application.id == AuditLog.entity_id)
        .filter(
            AuditLog.entity_type == "application",
            AuditLog.action == "onboarding_completed",
            Application.job_role_id == job_id,
        )
        .all()
    )
    if not rows:
        return None
    app_ids = [row.entity_id for row in rows]
    created_at_by_id = dict(
        db.query(Application.id, Application.created_at).filter(Application.id.in_(app_ids)).all()
    )
    deltas = [
        (completed_at - created_at_by_id[entity_id]).total_seconds() / 86400
        for entity_id, completed_at in rows
        if entity_id in created_at_by_id
    ]
    return round(sum(deltas) / len(deltas), 1) if deltas else None
