import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.jobs.service import close_job_if_deadline_passed
from app.models.application import APPLICATION_STATUSES, Application
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.reports import (
    ApplicationTimelineResponse,
    AuditLogPage,
    JobsDashboardStatsResponse,
    JobSummaryResponse,
    LabeledCount,
    PipelineResponse,
    StatusCount,
)

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
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    # Lazily enforce application deadlines before counting -- there's no
    # scheduler in this app, so a published job whose deadline has passed only
    # flips to 'closed' the next time something reads it (see app/jobs/service.py).
    # Without this pass, "Active Jobs"/"Open Positions" could still count a job
    # that every other read path already treats as closed.
    published_jobs = db.query(JobRole).filter(JobRole.status == "published").all()
    for job in published_jobs:
        close_job_if_deadline_passed(db, job)

    total_jobs = db.query(func.count(JobRole.id)).scalar() or 0
    active_jobs = (
        db.query(func.count(JobRole.id)).filter(JobRole.status == "published").scalar() or 0
    )
    open_positions = (
        db.query(func.coalesce(func.sum(JobRole.positions_count), 0))
        .filter(JobRole.status == "published")
        .scalar()
        or 0
    )
    total_applications = db.query(func.count(Application.id)).scalar() or 0

    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    next_month_start = (
        datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    )

    # applications.updated_at has no onupdate trigger (it's set once at insert and
    # never touched again), so it can't tell us *when* an application reached
    # onboarding_completed. The audit_log row that transition writes (see
    # app/offers/router.py complete_onboarding) is timestamped at the moment the
    # transition actually happened, so we use that instead for both the monthly
    # count and the time-to-hire calculation below.
    completion_rows = (
        db.query(AuditLog.entity_id, AuditLog.created_at)
        .filter(
            AuditLog.entity_type == "application",
            AuditLog.action == "onboarding_completed",
            AuditLog.created_at >= month_start,
            AuditLog.created_at < next_month_start,
        )
        .all()
    )
    hires_this_month = len(completion_rows)

    # Time to hire = days between application.created_at and the audit_log
    # timestamp of that same application's onboarding_completed transition,
    # averaged over completions recorded this calendar month.
    avg_time_to_hire_days = None
    if completion_rows:
        app_ids = [row.entity_id for row in completion_rows]
        created_at_by_id = dict(
            db.query(Application.id, Application.created_at)
            .filter(Application.id.in_(app_ids))
            .all()
        )
        deltas = [
            (completed_at - created_at_by_id[entity_id]).total_seconds() / 86400
            for entity_id, completed_at in completion_rows
            if entity_id in created_at_by_id
        ]
        if deltas:
            avg_time_to_hire_days = round(sum(deltas) / len(deltas), 1)

    department_label = func.coalesce(JobRole.department, "Unspecified")
    by_department = (
        db.query(department_label, func.count(JobRole.id)).group_by(department_label).all()
    )
    location_label = func.coalesce(JobRole.location, "Unspecified")
    by_location = db.query(location_label, func.count(JobRole.id)).group_by(location_label).all()

    return JobsDashboardStatsResponse(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        open_positions=int(open_positions),
        total_applications=total_applications,
        hires_this_month=hires_this_month,
        avg_time_to_hire_days=avg_time_to_hire_days,
        by_department=[LabeledCount(label=label, count=count) for label, count in by_department],
        by_location=[LabeledCount(label=label, count=count) for label, count in by_location],
    )


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
