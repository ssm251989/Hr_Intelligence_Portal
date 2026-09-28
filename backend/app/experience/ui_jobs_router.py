"""Part 15 step 15.4 -- Jobs screen helpers (docs/HRMS_COMPLETE_SPEC.txt section L, J4/J5).

* GET  /api/v1/ui/jobs/pipeline-summary -- per job: how many candidates sit in each hiring
  stage (J4 "job table with candidate counts per stage"), how many openings are filled, and
  when/why the job will close by itself (J5).
* POST /api/v1/ui/jobs/{job_id}/reopen -- J5 "recruiter can reopen" a closed job, optionally
  with a new closing date and/or more openings so it does not close again straight away.

J5 auto-close when positions are filled follows the same lazy, on-read pattern the existing
deadline rule uses (app/jobs/service.py close_job_if_deadline_passed -- there is no scheduler
in this app): the summary read closes a published job whose hired count has reached its
openings and writes an audit entry, which is what the Recent activity feed shows the
recruiter. Tenant scoping comes from the TenantOwned ORM read filter (+ Postgres RLS), same
as app/jobs/router.py.
"""

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.jobs.service import close_job_if_deadline_passed, get_application_deadline
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.models.user import User

router = APIRouter(prefix="/api/v1/ui/jobs", tags=["ui-jobs"])

# Application status -> the plain stage bucket the Jobs table shows. Every value of
# app/models/application.py APPLICATION_STATUSES is listed so nothing silently drops out.
STAGE_OF_STATUS: dict[str, str] = {
    "received": "new",
    "screened": "screening",
    "hr_selected": "shortlisted",
    "interview_scheduled": "interview",
    "interview_selected": "interview",
    "salary_ok": "offer",
    "salary_above_band": "offer",
    "salary_approved": "offer",
    "bgv_requested": "offer",
    "bgv_pending": "offer",
    "bgv_cleared": "offer",
    "offer_sent": "offer",
    "onboarding_started": "hired",
    "onboarding_completed": "hired",
    "hr_rejected": "not_selected",
    "interview_rejected": "not_selected",
    "salary_rejected": "not_selected",
    "bgv_rejected": "not_selected",
    "on_hold": "paused",
}
STAGES = ("new", "screening", "shortlisted", "interview", "offer", "hired", "not_selected", "paused")
AUTO_CLOSE_ACTIONS = ("job_auto_closed_deadline_passed", "job_auto_closed_positions_filled")


def _stage_counts(db: Session) -> dict[uuid.UUID, dict[str, int]]:
    rows = (
        db.query(Application.job_role_id, Application.status, func.count(Application.id))
        .filter(Application.job_role_id.isnot(None))
        .group_by(Application.job_role_id, Application.status)
        .all()
    )
    out: dict[uuid.UUID, dict[str, int]] = {}
    for job_id, status, count in rows:
        bucket = out.setdefault(job_id, {s: 0 for s in STAGES})
        bucket[STAGE_OF_STATUS.get(status or "", "new")] += int(count)
    return out


def close_job_if_positions_filled(db: Session, job: JobRole, hired: int) -> bool:
    """J5: a published job whose hired count reached its openings closes by itself."""
    positions = job.positions_count or 1
    if job.status != "published" or hired < positions:
        return False
    job.status = "closed"
    db.commit()
    db.refresh(job)
    log_action(
        db, "job_role", job.id, "job_auto_closed_positions_filled", "system",
        {"previous_status": "published", "positions_count": positions, "hired": hired},
    )
    return True


def _last_auto_close(db: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not job_ids:
        return {}
    rows = (
        db.query(AuditLog.entity_id, AuditLog.action, AuditLog.created_at)
        .filter(AuditLog.entity_type == "job_role", AuditLog.entity_id.in_(job_ids), AuditLog.action.in_(AUTO_CLOSE_ACTIONS))
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    out: dict[uuid.UUID, dict] = {}
    for entity_id, action, created_at in rows:  # ascending, so the latest wins
        out[entity_id] = {
            "reason": "positions_filled" if action == "job_auto_closed_positions_filled" else "deadline",
            "at": created_at.isoformat() if created_at else None,
        }
    return out


@router.get("/pipeline-summary")
def pipeline_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    counts = _stage_counts(db)
    jobs = db.query(JobRole).all()
    today = date.today()
    just_closed: list[str] = []
    items = []
    for job in jobs:
        stages = counts.get(job.id, {s: 0 for s in STAGES})
        hired = stages["hired"]
        if close_job_if_deadline_passed(db, job) or close_job_if_positions_filled(db, job, hired):
            just_closed.append(str(job.id))
        deadline = get_application_deadline(job)
        positions = job.positions_count or 1
        items.append({
            "job_id": str(job.id),
            "status": job.status,
            "stages": stages,
            "total": sum(stages.values()),
            "in_progress": sum(stages[s] for s in ("new", "screening", "shortlisted", "interview", "offer")),
            "hired": hired,
            "positions_count": positions,
            "positions_left": max(positions - hired, 0),
            "closes_on": deadline.isoformat() if deadline else None,
            "days_to_close": (deadline - today).days if deadline else None,
        })
    closed_ids = [job.id for job in jobs if job.status == "closed"]
    auto = _last_auto_close(db, closed_ids)
    for item in items:
        info = auto.get(uuid.UUID(item["job_id"])) if item["status"] == "closed" else None
        item["auto_closed"] = info
    return {"items": items, "just_closed": just_closed, "stages": list(STAGES)}


class ReopenRequest(BaseModel):
    application_deadline: Optional[date] = None
    positions_count: Optional[int] = None


@router.post("/{job_id}/reopen")
def reopen_job(
    job_id: uuid.UUID,
    payload: ReopenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    """closed -> published (live on the careers page again)."""
    job = db.get(JobRole, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job role not found")
    if job.status != "closed":
        raise HTTPException(status_code=400, detail="Only a closed job can be reopened.")
    if payload.application_deadline is not None and payload.application_deadline < date.today():
        raise HTTPException(status_code=400, detail="Pick a closing date that is today or later.")
    if payload.positions_count is not None:
        if payload.positions_count < 1:
            raise HTTPException(status_code=400, detail="Openings must be at least 1.")
        job.positions_count = payload.positions_count
    hired = _stage_counts(db).get(job.id, {}).get("hired", 0)
    if hired >= (job.positions_count or 1):
        raise HTTPException(status_code=400, detail="Every opening is already filled. Add more openings to reopen this job.")

    settings = dict(job.publish_settings or {})
    settings["application_deadline"] = payload.application_deadline.isoformat() if payload.application_deadline else None
    job.publish_settings = settings
    platforms = dict(job.published_platforms or {})
    platforms["career_portal"] = True
    job.published_platforms = platforms
    job.status = "published"
    db.commit()
    db.refresh(job)
    # Part 18.8: candidates the closing put on hold go back to the stage they were in
    from app.jobs.closing import restore_applications
    from app.platform.tenancy.context import require_current_tenant

    restored = restore_applications(db, require_current_tenant(), job, actor=current_user.email)
    log_action(
        db, "job_role", job.id, "job_reopened", "system",
        {"previous_status": "closed", "new_status": "published", "application_deadline": settings["application_deadline"],
         "positions_count": job.positions_count, "by": current_user.email, "applications_restored": restored},
    )
    return {"job_id": str(job.id), "status": job.status, "applications_restored": restored}


class CloseRequest(BaseModel):
    reason: str
    note: Optional[str] = None
    email_candidates: Optional[bool] = None  # None = the company setting


@router.post("/{job_id}/close")
def close_job(job_id: uuid.UUID, payload: CloseRequest, db: Session = Depends(get_db),
              current_user: User = Depends(require_roles("recruiter", "admin"))):
    """Part 18.8: close by hand -> active applications "On hold - job closed", pending emails/links cancelled."""
    from app.jobs.closing import close_job as do_close
    from app.platform.tenancy.context import require_current_tenant

    job = db.get(JobRole, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job role not found")
    try:
        return do_close(db, require_current_tenant(), job, reason=payload.reason, note=payload.note, actor=current_user.email,
                        email_candidates=payload.email_candidates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
