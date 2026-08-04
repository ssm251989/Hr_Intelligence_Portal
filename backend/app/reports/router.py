import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import APPLICATION_STATUSES, Application
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.reports import (
    ApplicationTimelineResponse,
    AuditLogPage,
    JobSummaryResponse,
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
