"""Part 18.11: one table of ALL candidates at a stage, across every job (no "choose a job first").

- GET /api/v1/ui/stage-table/{stage}          stage = salary | bgv | offers
      ?page&page_size (<=500)&sort=name|job|days|status|updated&dir=asc|desc&search&job_role_id&status&department
- GET /api/v1/ui/stage-table/{stage}/export   same filters -> CSV (every matching row)
Job is a column and a filter; each row carries the stage's own figures (documents checked,
offer signed, joining date ...). Tenant-scoped explicitly.
"""

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/stage-table", tags=["ui-stage-table"])

STAGES = {
    "salary": ("recruitment.salary.view", ("interview_selected", "salary_ok", "salary_above_band", "salary_approved", "salary_rejected")),
    "bgv": ("recruitment.bgv.view", ("salary_approved", "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected")),
    "offers": ("recruitment.offer.view", ("bgv_cleared", "offer_sent", "onboarding_started", "onboarding_completed")),
}


def _query(db, tenant, stage, *, search, job_role_id, status, department):
    statuses = STAGES[stage][1]
    q = (db.query(Application, Candidate, JobRole)
         .join(Candidate, Candidate.id == Application.candidate_id)
         .join(JobRole, JobRole.id == Application.job_role_id)
         .filter(Application.tenant_id == tenant.tenant_id, Application.status.in_(statuses)))
    if status:
        wanted = [s for s in status.split(",") if s in statuses]
        q = q.filter(Application.status.in_(wanted or ["-"]))
    if job_role_id:
        q = q.filter(Application.job_role_id == job_role_id)
    if department:
        q = q.filter(JobRole.department == department)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Candidate.full_name.ilike(like), Candidate.email.ilike(like), JobRole.title.ilike(like)))
    return q


def _extras(db, stage, app_ids) -> dict:
    out: dict = {i: {} for i in app_ids}
    if not app_ids:
        return out
    if stage == "bgv":
        from app.models.bgv_document import BgvDocument

        for aid, total, ok in db.query(BgvDocument.application_id, func.count(BgvDocument.id),
                                       func.count(BgvDocument.id).filter(BgvDocument.validation_status.in_(("valid", "verified", "approved")))
                                       ).filter(BgvDocument.application_id.in_(app_ids)).group_by(BgvDocument.application_id):
            out[aid] = {"documents": total, "documents_ok": ok}
    elif stage == "offers":
        from app.models.offer import Offer

        for o in db.query(Offer).filter(Offer.application_id.in_(app_ids)):
            out[o.application_id] = {"offer_signed": bool(o.signed), "joining_date": o.joining_date.isoformat() if o.joining_date else None,
                                     "offer_expires": o.expiry_date.isoformat() if o.expiry_date else None}
    elif stage == "salary":
        for a in db.query(Application).filter(Application.id.in_(app_ids)):
            check = a.salary_check or {}
            out[a.id] = {"expected_salary": float(a.expected_salary) if a.expected_salary is not None else None,
                         "approved_salary": float(a.approved_salary) if a.approved_salary is not None else None, "salary_state": check.get("state")}
    return out


def _row(app, cand, job, extra, now):
    since = app.updated_at or app.created_at
    return {"application_id": str(app.id), "candidate_id": str(cand.id), "name": cand.full_name, "email": cand.email,
            "job_id": str(job.id), "job": job.title, "department": job.department, "location": job.location, "status": app.status,
            "days_in_stage": (now - since).days if since else None, "updated_at": since.isoformat() if since else None, **extra}


def _guard(db, user, stage):
    if stage not in STAGES:
        raise HTTPException(status_code=404, detail="Unknown stage")
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, STAGES[stage][0]):
        raise HTTPException(status_code=403, detail=f"Missing permission: {STAGES[stage][0]}")
    return tenant


SORTS = {"name": Candidate.full_name, "job": JobRole.title, "status": Application.status,
         "days": func.coalesce(Application.updated_at, Application.created_at), "updated": func.coalesce(Application.updated_at, Application.created_at)}


@router.get("/{stage}")
def stage_table(stage: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                sort: Literal["name", "job", "days", "status", "updated"] = "days", dir: Literal["asc", "desc"] = "desc",
                search: Optional[str] = None, job_role_id: Optional[uuid.UUID] = None, status: Optional[str] = None, department: Optional[str] = None,
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _guard(db, current_user, stage)
    q = _query(db, tenant, stage, search=search, job_role_id=job_role_id, status=status, department=department)
    total = q.count()
    counts = dict(q.with_entities(Application.status, func.count(Application.id)).group_by(Application.status).all())
    col = SORTS[sort]
    # "days in stage" desc = waiting longest first = oldest update first
    order = col.asc() if (sort == "days") == (dir == "desc") else col.desc()
    rows = q.order_by(order, Application.id).offset((page - 1) * page_size).limit(page_size).all()
    now = datetime.now(timezone.utc)
    extras = _extras(db, stage, [a.id for a, _c, _j in rows])
    departments = sorted({d for (d,) in db.query(JobRole.department).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.department.isnot(None)).distinct()})
    return {"stage": stage, "statuses": list(STAGES[stage][1]), "total": total, "page": page, "page_size": page_size, "status_counts": counts,
            "departments": departments, "items": [_row(a, c, j, extras.get(a.id, {}), now) for a, c, j in rows]}


@router.get("/{stage}/export")
def stage_export(stage: str, search: Optional[str] = None, job_role_id: Optional[uuid.UUID] = None, status: Optional[str] = None,
                 department: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _guard(db, current_user, stage)
    rows = _query(db, tenant, stage, search=search, job_role_id=job_role_id, status=status, department=department).order_by(Candidate.full_name).limit(20000).all()
    now = datetime.now(timezone.utc)
    extras = _extras(db, stage, [a.id for a, _c, _j in rows])
    data = [_row(a, c, j, extras.get(a.id, {}), now) for a, c, j in rows]
    cols = ["name", "email", "job", "department", "location", "status", "days_in_stage"] + sorted({k for r in data for k in r} - {
        "name", "email", "job", "department", "location", "status", "days_in_stage", "application_id", "candidate_id", "job_id", "updated_at"})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(data)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{stage}-candidates.csv"'})
