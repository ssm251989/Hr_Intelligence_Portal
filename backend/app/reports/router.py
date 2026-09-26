import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.candidates.router import ScreeningAuditEntry, SuitableJob, _latest_screening_audit_id, row_to_item
from app.core.database import get_db
from app.jobs.service import close_job_if_deadline_passed
from app.models.application import APPLICATION_STATUSES, Application
from app.models.audit_log import AuditLog
from app.models.bgv_document import BgvDocument
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JOB_ROLE_STATUSES, JobRole
from app.models.user import User
from app.reports import stats
from app.scheduling.router import filtered_interviews_query, interview_row_to_item
from app.schemas.candidates_dashboard import (
    CandidateDataSourceStatus,
    CandidatesDashboardStatsResponse,
)
from app.schemas.interviews_dashboard import InterviewsDashboardStatsResponse
from app.schemas.reports import (
    ApplicationTimelineResponse,
    AuditLogPage,
    CandidateTimelineResponse,
    JobsDashboardStatsResponse,
    JobStatusOverviewResponse,
    JobSummaryResponse,
    LabeledCount,
    PipelineResponse,
    RecentActivityItem,
    RecentActivityResponse,
    StatusCount,
    TopJobItem,
)
from app.schemas.screening import ScreeningDashboardStatsResponse
from app.schemas.shortlisting import ShortlistFunnelStage, ShortlistingDashboardStatsResponse

router = APIRouter(tags=["reports"])

_STATUS_ORDER = {status: index for index, status in enumerate(APPLICATION_STATUSES)}


def _ordered_status_counts(rows: list[tuple[str, int]]) -> list[StatusCount]:
    counts = [StatusCount(status=status, count=count) for status, count in rows]
    return sorted(counts, key=lambda row: _STATUS_ORDER.get(row.status, len(_STATUS_ORDER)))


@router.get("/reports/pipeline", response_model=PipelineResponse)
def get_pipeline(
    job_role_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Application.status, func.count(Application.id))
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    rows = query.group_by(Application.status).all()

    by_status = _ordered_status_counts(rows)
    return PipelineResponse(total=sum(row.count for row in by_status), by_status=by_status)


@router.get("/reports/jobs/{job_id}/summary", response_model=JobSummaryResponse)
def get_job_summary(
    job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    job = db.get(JobRole, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    status_rows = (
        db.query(Application.status, func.count(Application.id))
        .filter(Application.job_role_id == job_id)
        .group_by(Application.status)
        .all()
    )
    by_status = _ordered_status_counts(status_rows)

    avg_match_score, avg_ranking_score = (
        db.query(func.avg(Application.match_score), func.avg(Application.ranking_score))
        .filter(Application.job_role_id == job_id)
        .one()
    )

    return JobSummaryResponse(
        job_role_id=job_id,
        total_applications=sum(row.count for row in by_status),
        by_status=by_status,
        average_match_score=float(avg_match_score) if avg_match_score is not None else None,
        average_ranking_score=float(avg_ranking_score) if avg_ranking_score is not None else None,
    )


@router.get("/reports/jobs-dashboard-stats", response_model=JobsDashboardStatsResponse)
def get_jobs_dashboard_stats(
    compare_month: Optional[str] = Query(
        None,
        description="YYYY-MM month to compare the current values against. Must be one "
        "of the past 12 completed months; defaults to last month.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Lazily enforce application deadlines before counting -- there's no
    # scheduler in this app, so a published job whose deadline has passed only
    # flips to 'closed' the next time something reads it (see app/jobs/service.py).
    # Without this pass, "Active Jobs"/"Open Positions" could still count a job
    # that every other read path already treats as closed.
    published_jobs = db.query(JobRole).filter(JobRole.status == "published").all()
    for job in published_jobs:
        close_job_if_deadline_passed(db, job)

    now = datetime.now(timezone.utc)
    try:
        compare_month_start = stats.parse_compare_month(compare_month, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    compare_month_end = stats.shift_months(compare_month_start, 1)

    # Last 12 calendar months, oldest first, ending with the current (in-progress) one --
    # the sparkline series. month_ends[i] is the exclusive upper bound ("as of month-end")
    # for month_starts[i]; the last entry is always > now, so it behaves as "no cutoff"
    # for the current-month point -- i.e. the true current value, not an approximation.
    month_starts = stats.last_12_month_starts(now)
    month_ends = [stats.shift_months(month_start, 1) for month_start in month_starts]
    current_month_start, current_month_end = month_starts[-1], month_ends[-1]

    total_jobs = stats.cumulative_count_as_of(db, JobRole, current_month_end)
    total_applications = stats.cumulative_count_as_of(db, Application, current_month_end)
    active_jobs, open_positions = stats.published_snapshot_as_of(db, current_month_end)

    # applications.updated_at has no onupdate trigger (it's set once at insert and
    # never touched again), so it can't tell us *when* an application reached
    # onboarding_completed. The audit_log row that transition writes (see
    # app/offers/router.py complete_onboarding) is timestamped at the moment the
    # transition actually happened, so we use that instead for both the monthly
    # count and the time-to-hire calculation below.
    hires_this_month, avg_time_to_hire_days = stats.hires_and_avg_time_to_hire(
        db, current_month_start, current_month_end
    )

    total_jobs_series = [stats.cumulative_count_as_of(db, JobRole, end) for end in month_ends]
    total_applications_series = [
        stats.cumulative_count_as_of(db, Application, end) for end in month_ends
    ]
    active_jobs_series: list[float] = []
    open_positions_series: list[float] = []
    for end in month_ends:
        active_snapshot, open_snapshot = stats.published_snapshot_as_of(db, end)
        active_jobs_series.append(active_snapshot)
        open_positions_series.append(open_snapshot)
    hires_series: list[float] = []
    avg_time_series: list[Optional[float]] = []
    for month_start_i, month_end_i in zip(month_starts, month_ends):
        month_hires, month_avg = stats.hires_and_avg_time_to_hire(db, month_start_i, month_end_i)
        hires_series.append(month_hires)
        avg_time_series.append(month_avg)

    compare_total_jobs = stats.cumulative_count_as_of(db, JobRole, compare_month_end)
    compare_total_applications = stats.cumulative_count_as_of(db, Application, compare_month_end)
    compare_active_jobs, compare_open_positions = stats.published_snapshot_as_of(
        db, compare_month_end
    )
    compare_hires, compare_avg_time = stats.hires_and_avg_time_to_hire(
        db, compare_month_start, compare_month_end
    )

    total_jobs_trend = stats.build_trend(
        month_starts, total_jobs_series, compare_month_start, compare_total_jobs, total_jobs
    )
    active_jobs_trend = stats.build_trend(
        month_starts,
        active_jobs_series,
        compare_month_start,
        compare_active_jobs,
        active_jobs,
        is_approximate=True,
    )
    open_positions_trend = stats.build_trend(
        month_starts,
        open_positions_series,
        compare_month_start,
        compare_open_positions,
        open_positions,
        is_approximate=True,
    )
    total_applications_trend = stats.build_trend(
        month_starts,
        total_applications_series,
        compare_month_start,
        compare_total_applications,
        total_applications,
    )
    hires_this_month_trend = stats.build_trend(
        month_starts, hires_series, compare_month_start, compare_hires, hires_this_month
    )
    avg_time_to_hire_trend = stats.build_trend(
        month_starts,
        avg_time_series,
        compare_month_start,
        compare_avg_time,
        avg_time_to_hire_days,
    )

    department_label = func.coalesce(JobRole.department, "Unspecified")
    by_department = (
        db.query(department_label, func.count(JobRole.id)).group_by(department_label).all()
    )
    location_label = func.coalesce(JobRole.location, "Unspecified")
    by_location = db.query(location_label, func.count(JobRole.id)).group_by(location_label).all()

    top_job_rows = (
        db.query(JobRole.id, JobRole.title, func.count(Application.id))
        .outerjoin(Application, Application.job_role_id == JobRole.id)
        .group_by(JobRole.id, JobRole.title)
        # Tied on application_count (routine for 0-application jobs, or any two jobs with
        # the same count) without a secondary key, Postgres is free to return those rows in
        # a different order from one query to the next -- job created_at (oldest first),
        # then id as a final tiebreaker for jobs created in the very same instant, makes
        # ties stable and reproducible.
        .order_by(func.count(Application.id).desc(), JobRole.created_at, JobRole.id)
        .limit(5)
        .all()
    )

    return JobsDashboardStatsResponse(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        open_positions=int(open_positions),
        total_applications=total_applications,
        hires_this_month=hires_this_month,
        avg_time_to_hire_days=avg_time_to_hire_days,
        total_jobs_trend=total_jobs_trend,
        active_jobs_trend=active_jobs_trend,
        open_positions_trend=open_positions_trend,
        total_applications_trend=total_applications_trend,
        hires_this_month_trend=hires_this_month_trend,
        avg_time_to_hire_trend=avg_time_to_hire_trend,
        by_department=[LabeledCount(label=label, count=count) for label, count in by_department],
        by_location=[LabeledCount(label=label, count=count) for label, count in by_location],
        top_jobs=[
            TopJobItem(job_id=job_id, title=title, application_count=count)
            for job_id, title, count in top_job_rows
        ],
    )


@router.get("/reports/job-status-overview", response_model=JobStatusOverviewResponse)
def get_job_status_overview(
    period: str = Query(
        "this_month",
        description=f"One of {stats.JOB_STATUS_OVERVIEW_PERIODS}; scopes the breakdown to jobs created in that window.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    try:
        period_start = stats.job_status_period_start(period, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    query = db.query(JobRole.status, func.count(JobRole.id))
    if period_start is not None:
        query = query.filter(JobRole.created_at >= period_start)
    rows = dict(query.group_by(JobRole.status).all())

    # Every real status always appears, even at 0 -- this is an "overview" of the full
    # status enum for the period, not just whichever statuses happen to have jobs in it.
    by_status = [LabeledCount(label=status, count=rows.get(status, 0)) for status in JOB_ROLE_STATUSES]
    return JobStatusOverviewResponse(period=period, total=sum(row.count for row in by_status), by_status=by_status)


def _humanize_action(action: Optional[str]) -> str:
    text = (action or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Activity"


def _describe_job_role_entry(db: Session, entry: AuditLog) -> str:
    job = db.get(JobRole, entry.entity_id) if entry.entity_id else None
    title = job.title if job else "a job"
    if entry.action == "job_role_created":
        return f"Job created: {title}"
    if entry.action == "job_platforms_published":
        new_status = (entry.details or {}).get("new_status")
        return f"Job published: {title}" if new_status == "published" else f"Job unpublished: {title}"
    if entry.action == "job_auto_closed_deadline_passed":
        return f"Job auto-closed (deadline passed): {title}"
    if entry.action == "job_auto_closed_positions_filled":
        return f"Job auto-closed (all positions filled): {title}"
    if entry.action == "job_reopened":
        return f"Job reopened: {title}"
    return f"{_humanize_action(entry.action)}: {title}"


def _describe_application_entry(db: Session, entry: AuditLog) -> str:
    application = db.get(Application, entry.entity_id) if entry.entity_id else None
    candidate_name = "A candidate"
    job_title = "a job"
    if application:
        candidate = db.get(Candidate, application.candidate_id)
        if candidate and candidate.full_name:
            candidate_name = candidate.full_name
        job = db.get(JobRole, application.job_role_id)
        if job:
            job_title = job.title
    if entry.action == "application_created":
        return f"New application: {candidate_name} for {job_title}"
    if entry.action == "onboarding_completed":
        return f"Hire completed: {candidate_name} for {job_title}"
    return f"{_humanize_action(entry.action)}: {candidate_name} — {job_title}"


@router.get("/reports/recent-activity", response_model=RecentActivityResponse)
def get_recent_activity(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human-readable activity feed for the dashboard + header notification bell.

    Scoped to job/application audit_log rows (the two entity types recruiters care
    about day to day) and resolves job titles/candidate names server-side so the
    frontend doesn't need N+1 lookups. Only a handful of well-known actions per
    entity type get a tailored message; anything else falls back to a humanized
    version of the raw action string rather than going unlabeled.
    """
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type.in_(["job_role", "application"]))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    items = []
    for entry in entries:
        message = (
            _describe_job_role_entry(db, entry)
            if entry.entity_type == "job_role"
            else _describe_application_entry(db, entry)
        )
        items.append(
            RecentActivityItem(
                id=entry.id,
                created_at=entry.created_at,
                message=message,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
            )
        )
    return RecentActivityResponse(items=items)


@router.get("/reports/audit", response_model=AuditLogPage)
def list_audit_log(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[uuid.UUID] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AuditLog)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if action is not None:
        query = query.filter(AuditLog.action == action)

    total = query.count()
    items = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return AuditLogPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/applications/{application_id}/timeline", response_model=ApplicationTimelineResponse)
def get_application_timeline(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    events = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == application_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return ApplicationTimelineResponse(application_id=application_id, events=events)


def _candidate_data_sources(db: Session) -> list[CandidateDataSourceStatus]:
    """Real connection status per sourcing channel -- Career Portal is always connected
    (it's this app's own pipeline); Local Import is connected only once an import has
    actually run; LinkedIn/Naukri have no real candidate-import access at all (separate
    from the job-posting LinkedIn integration elsewhere in this app, which doesn't grant
    candidate import), so they're never shown as connected."""
    career_portal_last_sync = (
        db.query(func.max(Candidate.created_at)).filter(Candidate.source == "career_portal").scalar()
    )
    local_import_last_sync = (
        db.query(func.max(Candidate.created_at)).filter(Candidate.source == "local_import").scalar()
    )
    return [
        CandidateDataSourceStatus(
            source="career_portal", label="Career Portal", connected=True, last_sync=career_portal_last_sync
        ),
        CandidateDataSourceStatus(
            source="local_import",
            label="Local Import",
            connected=local_import_last_sync is not None,
            last_sync=local_import_last_sync,
        ),
        CandidateDataSourceStatus(source="linkedin", label="LinkedIn", connected=False, last_sync=None),
        CandidateDataSourceStatus(source="naukri", label="Naukri", connected=False, last_sync=None),
    ]


@router.get("/reports/candidates-dashboard-stats", response_model=CandidatesDashboardStatsResponse)
def get_candidates_dashboard_stats(
    compare_month: Optional[str] = Query(
        None,
        description="YYYY-MM month to compare the current values against. Must be one "
        "of the past 12 completed months; defaults to last month.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    try:
        compare_month_start = stats.parse_compare_month(compare_month, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    compare_month_end = stats.shift_months(compare_month_start, 1)

    month_starts = stats.last_12_month_starts(now)
    month_ends = [stats.shift_months(month_start, 1) for month_start in month_starts]
    current_month_start, current_month_end = month_starts[-1], month_ends[-1]

    total_candidates = stats.cumulative_count_as_of(db, Candidate, current_month_end)
    new_this_month = stats.count_created_in_window(db, Candidate, current_month_start, current_month_end)

    total_candidates_series = [stats.cumulative_count_as_of(db, Candidate, end) for end in month_ends]
    new_this_month_series = [
        stats.count_created_in_window(db, Candidate, start, end) for start, end in zip(month_starts, month_ends)
    ]

    compare_total_candidates = stats.cumulative_count_as_of(db, Candidate, compare_month_end)
    compare_new_candidates = stats.count_created_in_window(db, Candidate, compare_month_start, compare_month_end)

    total_candidates_trend = stats.build_trend(
        month_starts, total_candidates_series, compare_month_start, compare_total_candidates, total_candidates
    )
    new_this_month_trend = stats.build_trend(
        month_starts, new_this_month_series, compare_month_start, compare_new_candidates, new_this_month
    )

    avg_match_score_series = [stats.avg_match_score_as_of(db, end) for end in month_ends]
    avg_match_score = avg_match_score_series[-1]
    compare_avg_match_score = stats.avg_match_score_as_of(db, compare_month_end)
    avg_match_score_trend = stats.build_trend(
        month_starts, avg_match_score_series, compare_month_start, compare_avg_match_score, avg_match_score
    )

    source_counts = dict(stats.candidate_source_breakdown(db))
    from_career_portal = source_counts.get("career_portal", 0)
    manually_added = sum(source_counts.get(source, 0) for source in stats.MANUALLY_ADDED_SOURCES)
    active_candidates = stats.active_candidates_count(db)

    from_career_portal_series: list[float] = []
    manually_added_series: list[float] = []
    for end in month_ends:
        counts_as_of = stats.candidate_source_counts_as_of(db, end)
        from_career_portal_series.append(counts_as_of.get("career_portal", 0))
        manually_added_series.append(sum(counts_as_of.get(source, 0) for source in stats.MANUALLY_ADDED_SOURCES))

    compare_source_counts = stats.candidate_source_counts_as_of(db, compare_month_end)
    compare_from_career_portal = compare_source_counts.get("career_portal", 0)
    compare_manually_added = sum(compare_source_counts.get(source, 0) for source in stats.MANUALLY_ADDED_SOURCES)

    from_career_portal_trend = stats.build_trend(
        month_starts, from_career_portal_series, compare_month_start, compare_from_career_portal, from_career_portal
    )
    manually_added_trend = stats.build_trend(
        month_starts, manually_added_series, compare_month_start, compare_manually_added, manually_added
    )

    data_sources = _candidate_data_sources(db)

    recent_rows = (
        db.query(
            Application, Candidate, JobRole.title, SuitableJob.title,
            ScreeningAuditEntry.action, ScreeningAuditEntry.details,
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .outerjoin(SuitableJob, SuitableJob.id == Candidate.suitable_job_id)
        .outerjoin(ScreeningAuditEntry, ScreeningAuditEntry.id == _latest_screening_audit_id(db))
        .order_by(Application.created_at.desc())
        .limit(8)
        .all()
    )

    return CandidatesDashboardStatsResponse(
        total_candidates=total_candidates,
        new_this_month=new_this_month,
        from_career_portal=from_career_portal,
        manually_added=manually_added,
        active_candidates=active_candidates,
        avg_match_score=avg_match_score,
        total_candidates_trend=total_candidates_trend,
        new_this_month_trend=new_this_month_trend,
        from_career_portal_trend=from_career_portal_trend,
        manually_added_trend=manually_added_trend,
        avg_match_score_trend=avg_match_score_trend,
        by_source=[LabeledCount(label=source, count=count) for source, count in stats.candidate_source_breakdown(db)],
        top_skills=[LabeledCount(label=skill, count=count) for skill, count in stats.top_skills(db, limit=5)],
        match_score_distribution=[
            LabeledCount(label=bucket, count=count) for bucket, count in stats.match_score_distribution(db)
        ],
        data_sources=data_sources,
        recent_candidates=[
            row_to_item(app, cand, title, suitable_title, screening_action, screening_details)
            for app, cand, title, suitable_title, screening_action, screening_details in recent_rows
        ],
    )


_RECOMMENDATION_BUCKETS = ("strong_fit", "possible_fit", "weak_fit")
_RECOMMENDATION_DISPLAY = {"strong_fit": "Strong fit", "possible_fit": "Possible fit", "weak_fit": "Weak fit"}


def _recommendation_breakdown(db: Session) -> list[LabeledCount]:
    """Every application's LATEST screening entry (same "latest per application" join the
    Candidates List's Remarks column uses -- see _latest_screening_audit_id), bucketed by
    its recommendation. Only counts applications whose latest entry is an actual
    ai_screening_scored result (an inner join naturally excludes anyone never screened, or
    whose latest attempt failed) -- all 3 buckets always appear, even at 0."""
    recommendation_col = ScreeningAuditEntry.details["recommendation"].astext
    rows = (
        db.query(recommendation_col, func.count(Application.id))
        .select_from(Application)
        .join(ScreeningAuditEntry, ScreeningAuditEntry.id == _latest_screening_audit_id(db))
        .filter(ScreeningAuditEntry.action == "ai_screening_scored")
        .group_by(recommendation_col)
        .all()
    )
    counts = dict(rows)
    return [
        LabeledCount(label=_RECOMMENDATION_DISPLAY[key], count=counts.get(key, 0))
        for key in _RECOMMENDATION_BUCKETS
    ]


@router.get("/reports/screening-dashboard-stats", response_model=ScreeningDashboardStatsResponse)
def get_screening_dashboard_stats(
    compare_month: Optional[str] = Query(
        None,
        description="YYYY-MM month to compare the current values against. Must be one "
        "of the past 12 completed months; defaults to last month.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    try:
        compare_month_start = stats.parse_compare_month(compare_month, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    compare_month_end = stats.shift_months(compare_month_start, 1)

    month_starts = stats.last_12_month_starts(now)
    month_ends = [stats.shift_months(month_start, 1) for month_start in month_starts]
    current_month_start, current_month_end = month_starts[-1], month_ends[-1]

    awaiting_screening = stats.awaiting_screening_count(db)
    awaiting_ranking = stats.awaiting_ranking_count(db)

    auto_advanced_this_month = stats.screening_audit_count_in_window(
        db, "ai_screening_scored", current_month_start, current_month_end, advanced=True
    )
    auto_advanced_series = [
        stats.screening_audit_count_in_window(db, "ai_screening_scored", start, end, advanced=True)
        for start, end in zip(month_starts, month_ends)
    ]
    compare_auto_advanced = stats.screening_audit_count_in_window(
        db, "ai_screening_scored", compare_month_start, compare_month_end, advanced=True
    )
    auto_advanced_this_month_trend = stats.build_trend(
        month_starts, auto_advanced_series, compare_month_start, compare_auto_advanced, auto_advanced_this_month
    )

    failed_this_month = stats.screening_audit_count_in_window(
        db, "ai_screening_failed", current_month_start, current_month_end
    )
    failed_series = [
        stats.screening_audit_count_in_window(db, "ai_screening_failed", start, end)
        for start, end in zip(month_starts, month_ends)
    ]
    compare_failed = stats.screening_audit_count_in_window(
        db, "ai_screening_failed", compare_month_start, compare_month_end
    )
    failed_this_month_trend = stats.build_trend(
        month_starts, failed_series, compare_month_start, compare_failed, failed_this_month
    )

    avg_composite_score_series = [stats.avg_composite_score_as_of(db, end) for end in month_ends]
    avg_composite_score = avg_composite_score_series[-1]
    compare_avg_composite_score = stats.avg_composite_score_as_of(db, compare_month_end)
    avg_composite_score_trend = stats.build_trend(
        month_starts, avg_composite_score_series, compare_month_start, compare_avg_composite_score, avg_composite_score
    )

    return ScreeningDashboardStatsResponse(
        awaiting_screening=awaiting_screening,
        awaiting_ranking=awaiting_ranking,
        auto_advanced_this_month=auto_advanced_this_month,
        failed_this_month=failed_this_month,
        avg_composite_score=avg_composite_score,
        auto_advanced_this_month_trend=auto_advanced_this_month_trend,
        failed_this_month_trend=failed_this_month_trend,
        avg_composite_score_trend=avg_composite_score_trend,
        recommendation_breakdown=_recommendation_breakdown(db),
        composite_score_distribution=[
            LabeledCount(label=bucket, count=count) for bucket, count in stats.composite_score_distribution(db)
        ],
        top_missing_skills=[
            LabeledCount(label=skill, count=count) for skill, count in stats.top_missing_skills(db, limit=5)
        ],
    )


@router.get("/reports/candidates-top-skills", response_model=list[LabeledCount])
def get_candidates_top_skills(
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Omit for every distinct skill"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Backs the dashboard's "View all skills" link -- the dashboard-stats endpoint itself
    only ever returns the top 5, so this is a separate call rather than re-fetching the
    whole dashboard payload just to see more skills."""
    return [LabeledCount(label=skill, count=count) for skill, count in stats.top_skills(db, limit=limit)]


@router.get("/candidates/{candidate_id}/timeline", response_model=CandidateTimelineResponse)
def get_candidate_timeline(
    candidate_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Unions audit_log rows for the candidate itself, every application they've submitted,
    and every interview/BGV document tied to those applications -- the entity types that
    can appear in a candidate's history but are logged under their own id rather than the
    application's (see app/scheduling/router.py and app/bgv/router.py)."""
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    application_ids = [
        row[0] for row in db.query(Application.id).filter(Application.candidate_id == candidate_id).all()
    ]
    interview_ids = (
        [row[0] for row in db.query(Interview.id).filter(Interview.application_id.in_(application_ids)).all()]
        if application_ids
        else []
    )
    bgv_document_ids = (
        [row[0] for row in db.query(BgvDocument.id).filter(BgvDocument.application_id.in_(application_ids)).all()]
        if application_ids
        else []
    )

    conditions = [and_(AuditLog.entity_type == "candidate", AuditLog.entity_id == candidate_id)]
    if application_ids:
        conditions.append(and_(AuditLog.entity_type == "application", AuditLog.entity_id.in_(application_ids)))
    if interview_ids:
        conditions.append(and_(AuditLog.entity_type == "interview", AuditLog.entity_id.in_(interview_ids)))
    if bgv_document_ids:
        conditions.append(and_(AuditLog.entity_type == "bgv_document", AuditLog.entity_id.in_(bgv_document_ids)))

    events = db.query(AuditLog).filter(or_(*conditions)).order_by(AuditLog.created_at.asc()).all()
    return CandidateTimelineResponse(candidate_id=candidate_id, events=events)


# Every status downstream of a shortlisting decision -- used only to detect "did this
# application progress past hr_selected," never to imply shortlisting caused it.
_DOWNSTREAM_OF_SHORTLIST = (
    "interview_scheduled", "interview_selected", "interview_rejected",
    "salary_ok", "salary_above_band", "salary_approved", "salary_rejected",
    "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected",
    "offer_sent", "onboarding_started", "onboarding_completed",
)


def _shortlisting_insights(db: Session, month_start: datetime, month_end: datetime) -> list[str]:
    """Every sentence here traces to one real, literal SQL aggregate computed at request
    time -- never AI-generated or hand-authored copy. An insight is only ever included when
    its underlying query actually has data to report (no placeholder "N/A" sentences)."""
    insights: list[str] = []

    # 1. Per-job: of that job's currently-Shortlisted (hr_selected) candidates, what % scored
    # above 85 on the real composite score -- the job with the highest such percentage.
    high_score_rows = (
        db.query(
            JobRole.title,
            func.count(Application.id),
            func.sum(case((Application.composite_score > 85, 1), else_=0)),
        )
        .join(Application, Application.job_role_id == JobRole.id)
        .filter(Application.status == "hr_selected", Application.composite_score.isnot(None))
        .group_by(JobRole.title)
        .all()
    )
    best_pct, best_job = 0, None
    for title, total, above_85 in high_score_rows:
        if total > 0:
            pct = round(int(above_85) / total * 100)
            if pct > best_pct:
                best_pct, best_job = pct, title
    if best_job:
        insights.append(f"{best_pct}% of shortlisted candidates for {best_job} scored above 85.")

    # 2. Per-job shortlist-to-interview conversion, among applications created this month --
    # the job with the highest share of its hr_selected-or-later applicants that actually
    # progressed to interview_scheduled or beyond.
    conversion_rows = (
        db.query(JobRole.title, Application.status, func.count(Application.id))
        .join(Application, Application.job_role_id == JobRole.id)
        .filter(
            Application.status.in_(("hr_selected",) + _DOWNSTREAM_OF_SHORTLIST),
            Application.created_at >= month_start,
            Application.created_at < month_end,
        )
        .group_by(JobRole.title, Application.status)
        .all()
    )
    totals_by_job: dict[str, int] = {}
    interviewed_by_job: dict[str, int] = {}
    for title, status, count in conversion_rows:
        totals_by_job[title] = totals_by_job.get(title, 0) + count
        if status in _DOWNSTREAM_OF_SHORTLIST:
            interviewed_by_job[title] = interviewed_by_job.get(title, 0) + count
    best_conv_pct, best_conv_job = 0, None
    for title, total in totals_by_job.items():
        pct = round(interviewed_by_job.get(title, 0) / total * 100)
        if pct > best_conv_pct:
            best_conv_pct, best_conv_job = pct, title
    if best_conv_job:
        insights.append(f"{best_conv_job} has the highest shortlist-to-interview conversion this month ({best_conv_pct}%).")

    # 3. Most common Not Shortlisted reason this month, from real evaluator-recorded reasons
    # (Update Shortlist Status's Reason dropdown -- see app/shortlisting/service.py).
    reason_col = AuditLog.details["reason"].astext
    reason_rows = (
        db.query(reason_col, func.count(AuditLog.id))
        .filter(
            AuditLog.entity_type == "application",
            AuditLog.action == "shortlist_status_updated",
            AuditLog.details["new_application_status"].astext == "hr_rejected",
            AuditLog.created_at >= month_start,
            AuditLog.created_at < month_end,
            reason_col.isnot(None),
        )
        .group_by(reason_col)
        .order_by(func.count(AuditLog.id).desc())
        .all()
    )
    if reason_rows:
        top_reason, top_reason_count = reason_rows[0]
        plural = "s" if top_reason_count != 1 else ""
        insights.append(f'Most common Not Shortlisted reason this month: "{top_reason}" ({top_reason_count} candidate{plural}).')

    return insights


@router.get("/reports/shortlisting-dashboard-stats", response_model=ShortlistingDashboardStatsResponse)
def get_shortlisting_dashboard_stats(
    compare_month: Optional[str] = Query(
        None,
        description="YYYY-MM month to compare the current values against. Must be one "
        "of the past 12 completed months; defaults to last month.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    try:
        compare_month_start = stats.parse_compare_month(compare_month, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    compare_month_end = stats.shift_months(compare_month_start, 1)

    month_starts = stats.last_12_month_starts(now)
    month_ends = [stats.shift_months(month_start, 1) for month_start in month_starts]
    current_month_start, current_month_end = month_starts[-1], month_ends[-1]

    total_in_shortlisting = stats.awaiting_shortlist_decision_count(db)

    new_this_month = stats.shortlisting_new_in_scope_count_in_window(db, current_month_start, current_month_end)
    new_this_month_series = [
        stats.shortlisting_new_in_scope_count_in_window(db, s, e) for s, e in zip(month_starts, month_ends)
    ]
    compare_new_this_month = stats.shortlisting_new_in_scope_count_in_window(db, compare_month_start, compare_month_end)
    new_this_month_trend = stats.build_trend(
        month_starts, new_this_month_series, compare_month_start, compare_new_this_month, new_this_month
    )

    moved_from_screening_this_month = stats.screening_audit_count_in_window(
        db, "ai_screening_scored", current_month_start, current_month_end, advanced=True
    )
    moved_series = [
        stats.screening_audit_count_in_window(db, "ai_screening_scored", s, e, advanced=True)
        for s, e in zip(month_starts, month_ends)
    ]
    compare_moved = stats.screening_audit_count_in_window(
        db, "ai_screening_scored", compare_month_start, compare_month_end, advanced=True
    )
    moved_from_screening_this_month_trend = stats.build_trend(
        month_starts, moved_series, compare_month_start, compare_moved, moved_from_screening_this_month
    )

    shortlisted_this_month = stats.shortlisted_decision_count_in_window(db, current_month_start, current_month_end)
    shortlisted_series = [
        stats.shortlisted_decision_count_in_window(db, s, e) for s, e in zip(month_starts, month_ends)
    ]
    compare_shortlisted = stats.shortlisted_decision_count_in_window(db, compare_month_start, compare_month_end)
    shortlisted_this_month_trend = stats.build_trend(
        month_starts, shortlisted_series, compare_month_start, compare_shortlisted, shortlisted_this_month
    )

    avg_composite_series = [stats.avg_composite_score_of_status_as_of(db, "hr_selected", end) for end in month_ends]
    avg_composite_score_shortlisted = avg_composite_series[-1]
    compare_avg_composite = stats.avg_composite_score_of_status_as_of(db, "hr_selected", compare_month_end)
    avg_composite_score_shortlisted_trend = stats.build_trend(
        month_starts, avg_composite_series, compare_month_start, compare_avg_composite, avg_composite_score_shortlisted
    )

    funnel = [ShortlistFunnelStage(label=label, count=count) for label, count in stats.shortlisting_funnel_counts(db)]

    recent_rows = (
        db.query(
            Application, Candidate, JobRole.title, SuitableJob.title,
            ScreeningAuditEntry.action, ScreeningAuditEntry.details,
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .outerjoin(SuitableJob, SuitableJob.id == Candidate.suitable_job_id)
        .outerjoin(ScreeningAuditEntry, ScreeningAuditEntry.id == _latest_screening_audit_id(db))
        .filter(Application.status == "hr_selected")
        .order_by(Application.updated_at.desc())
        .limit(8)
        .all()
    )

    return ShortlistingDashboardStatsResponse(
        total_in_shortlisting=total_in_shortlisting,
        new_this_month=new_this_month,
        moved_from_screening_this_month=moved_from_screening_this_month,
        shortlisted_this_month=shortlisted_this_month,
        avg_composite_score_shortlisted=avg_composite_score_shortlisted,
        new_this_month_trend=new_this_month_trend,
        moved_from_screening_this_month_trend=moved_from_screening_this_month_trend,
        shortlisted_this_month_trend=shortlisted_this_month_trend,
        avg_composite_score_shortlisted_trend=avg_composite_score_shortlisted_trend,
        funnel=funnel,
        composite_score_distribution=[
            LabeledCount(label=bucket, count=count) for bucket, count in stats.composite_score_distribution(db)
        ],
        insights=_shortlisting_insights(db, current_month_start, current_month_end),
        recent_shortlisted=[
            row_to_item(app, cand, title, suitable_title, screening_action, screening_details)
            for app, cand, title, suitable_title, screening_action, screening_details in recent_rows
        ],
    )


@router.get("/reports/interviews-dashboard-stats", response_model=InterviewsDashboardStatsResponse)
def get_interviews_dashboard_stats(
    compare_month: Optional[str] = Query(
        None,
        description="YYYY-MM month to compare the current values against. Must be one "
        "of the past 12 completed months; defaults to last month.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    try:
        compare_month_start = stats.parse_compare_month(compare_month, now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    compare_month_end = stats.shift_months(compare_month_start, 1)

    month_starts = stats.last_12_month_starts(now)
    month_ends = [stats.shift_months(month_start, 1) for month_start in month_starts]
    current_month_start, current_month_end = month_starts[-1], month_ends[-1]

    total_this_month = stats.count_created_in_window(db, Interview, current_month_start, current_month_end)
    total_series = [
        stats.count_created_in_window(db, Interview, start, end) for start, end in zip(month_starts, month_ends)
    ]
    compare_total = stats.count_created_in_window(db, Interview, compare_month_start, compare_month_end)
    total_this_month_trend = stats.build_trend(
        month_starts, total_series, compare_month_start, compare_total, total_this_month
    )

    upcoming = stats.upcoming_interviews_count(db, now)

    completed = stats.completed_interviews_count_as_of(db, current_month_end)
    completed_series = [stats.completed_interviews_count_as_of(db, end) for end in month_ends]
    compare_completed = stats.completed_interviews_count_as_of(db, compare_month_end)
    completed_trend = stats.build_trend(
        month_starts, completed_series, compare_month_start, compare_completed, completed, is_approximate=True
    )

    selected = stats.interview_decision_count_as_of(db, "selected", current_month_end)
    selected_series = [stats.interview_decision_count_as_of(db, "selected", end) for end in month_ends]
    compare_selected = stats.interview_decision_count_as_of(db, "selected", compare_month_end)
    selected_trend = stats.build_trend(
        month_starts, selected_series, compare_month_start, compare_selected, selected, is_approximate=True
    )

    rejected = stats.interview_decision_count_as_of(db, "rejected", current_month_end)
    rejected_series = [stats.interview_decision_count_as_of(db, "rejected", end) for end in month_ends]
    compare_rejected = stats.interview_decision_count_as_of(db, "rejected", compare_month_end)
    rejected_trend = stats.build_trend(
        month_starts, rejected_series, compare_month_start, compare_rejected, rejected, is_approximate=True
    )

    recent_rows = (
        filtered_interviews_query(
            db,
            job_role_id=None,
            interviewer_id=None,
            status=None,
            scheduling_method=None,
            scheduled_after=None,
            scheduled_before=None,
            now=now,
        )
        .order_by(Interview.created_at.desc())
        .limit(8)
        .all()
    )

    return InterviewsDashboardStatsResponse(
        total_interviews_scheduled_this_month=total_this_month,
        upcoming=upcoming,
        completed=completed,
        selected=selected,
        rejected=rejected,
        total_interviews_scheduled_this_month_trend=total_this_month_trend,
        completed_trend=completed_trend,
        selected_trend=selected_trend,
        rejected_trend=rejected_trend,
        outcome_breakdown=[LabeledCount(label=label, count=count) for label, count in stats.interview_outcome_breakdown(db)],
        interviewer_workload=[
            LabeledCount(label=label, count=count) for label, count in stats.interviewer_workload(db, limit=10)
        ],
        scheduling_method_breakdown=[
            LabeledCount(label=label, count=count) for label, count in stats.scheduling_method_breakdown(db)
        ],
        recent_interviews=[
            interview_row_to_item(interview, application, candidate, job_title, interviewer, computed_status)
            for interview, application, candidate, job_title, interviewer, computed_status in recent_rows
        ],
    )
