"""Monthly time-series + comparison-month math behind the jobs dashboard stat cards.

Kept separate from app/reports/router.py so the month-bucketing and percentage-change
logic can be reasoned about (and tested) independently of the FastAPI/session wiring.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import TERMINAL_APPLICATION_STATUSES, Application
from app.models.audit_log import AuditLog
from app.models.candidate import CANDIDATE_SOURCES, Candidate
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


def count_created_in_window(db: Session, model, start: datetime, end: datetime) -> int:
    """New rows of `model` created within [start, end) -- the monthly-count counterpart to
    cumulative_count_as_of's running total. Works for any model with a created_at column."""
    return (
        db.query(func.count(model.id)).filter(model.created_at >= start, model.created_at < end).scalar() or 0
    )


# "Manually Added" folds local_import into manual: both are internal, recruiter-initiated
# creation paths (as opposed to career_portal, or a future sourcing integration), even
# though the source breakdown below keeps them as distinct labels.
MANUALLY_ADDED_SOURCES = ("manual", "local_import")


def active_candidates_count(db: Session) -> int:
    """Candidates with at least one application not yet in a terminal status. A candidate
    with zero applications (uploaded but never linked to a job) does not count as active --
    there's no in-flight pipeline to be active in."""
    return (
        db.query(func.count(func.distinct(Application.candidate_id)))
        .filter(~Application.status.in_(TERMINAL_APPLICATION_STATUSES))
        .scalar()
        or 0
    )


def candidate_source_breakdown(db: Session) -> list[tuple[str, int]]:
    """Every defined source always appears, even at 0 -- so LinkedIn/Naukri/Indeed/Monster/
    Shine show up as real (zero) slices the moment those integrations start writing
    candidates, with no schema or endpoint change needed here."""
    counts = dict(db.query(Candidate.source, func.count(Candidate.id)).group_by(Candidate.source).all())
    return [(source, counts.get(source, 0)) for source in CANDIDATE_SOURCES]


def candidate_source_counts_as_of(db: Session, cutoff: datetime) -> dict[str, int]:
    """Per-source candidate counts among candidates created before `cutoff` -- the
    "From Career Portals" / "Manually Added" trend counterpart to candidate_source_breakdown
    (which is always all-time), used to build monthly cumulative series for those cards."""
    return dict(
        db.query(Candidate.source, func.count(Candidate.id))
        .filter(Candidate.created_at < cutoff)
        .group_by(Candidate.source)
        .all()
    )


def top_skills(db: Session, limit: Optional[int] = 10) -> list[tuple[str, int]]:
    """Skill frequency across every candidate's parsed_fields.skills, sorted descending.
    `limit=None` returns every distinct skill (Counter.most_common(None) sorts the full
    set rather than truncating) -- used for the "view all skills" list. Done in Python
    (rather than a jsonb_array_elements SQL aggregate) since candidate counts here are
    small and it keeps the counting logic portable/testable without a live Postgres
    JSONB-specific query."""
    counter: Counter = Counter()
    rows = db.query(Candidate.parsed_fields).filter(Candidate.parsed_fields.isnot(None)).all()
    for (parsed_fields,) in rows:
        for skill in (parsed_fields or {}).get("skills") or []:
            if skill:
                counter[skill] += 1
    return counter.most_common(limit)


MATCH_SCORE_BUCKETS = ("90-100", "70-89", "50-69", "30-49", "0-29")


def _match_score_bucket(score: float) -> str:
    if score >= 90:
        return "90-100"
    if score >= 70:
        return "70-89"
    if score >= 50:
        return "50-69"
    if score >= 30:
        return "30-49"
    return "0-29"


def match_score_distribution(db: Session) -> list[tuple[str, int]]:
    """Buckets every application's real match_score -- all 5 buckets always appear, even
    at 0, so the chart's axis never reflows as data comes in."""
    counter: Counter = Counter()
    scores = db.query(Application.match_score).filter(Application.match_score.isnot(None)).all()
    for (score,) in scores:
        counter[_match_score_bucket(float(score))] += 1
    return [(bucket, counter.get(bucket, 0)) for bucket in MATCH_SCORE_BUCKETS]


def avg_match_score_as_of(db: Session, cutoff: datetime) -> Optional[float]:
    """Average real match_score across every application created before `cutoff` -- the
    candidates-dashboard counterpart to cumulative_count_as_of, but averaging instead of
    counting. None once no scored applications exist yet by that cutoff (a percentage
    average from zero scored applications is undefined, not 0)."""
    avg = (
        db.query(func.avg(Application.match_score))
        .filter(Application.match_score.isnot(None), Application.created_at < cutoff)
        .scalar()
    )
    return round(float(avg), 1) if avg is not None else None


