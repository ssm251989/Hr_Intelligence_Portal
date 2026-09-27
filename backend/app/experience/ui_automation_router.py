"""Part 17.13 API: talent pool, duplicates, job health, reminders, candidate status page.

- GET  /api/v1/ui/jobs/{id}/talent-pool                    past candidates scored for this job
- POST /api/v1/ui/jobs/{id}/talent-pool/{candidate_id}     add one of them to the job (Screened, scored)
- GET  /api/v1/ui/jobs-health                              open jobs needing attention + suggestions
- GET  /api/v1/ui/candidates/{id}/duplicates               possible earlier records of the same person
- GET  /api/v1/ui/system-health                            admin health page
- POST /api/v1/ui/reminders/run                            send due reminders now (admins; also hourly)
- GET  /api/v1/ui/applications/{id}/status-link            the candidate's own status page link (to share)
- GET  /api/v1/public/status/{token}                       the candidate's status page (no login)
Every query filters on the current company's tenant_id explicitly.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import automation

router = APIRouter(prefix="/api/v1/ui", tags=["ui-automation"])
public_router = APIRouter(prefix="/api/v1/public/status", tags=["candidate-status-public"])


def _need(db, tenant, user, permission: str) -> None:
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


def _job(db, tenant, job_id: UUID) -> JobRole:
    job = db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/talent-pool")
def talent_pool(job_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    return automation.talent_pool(db, tenant, _job(db, tenant, job_id))


@router.post("/jobs/{job_id}/talent-pool/{candidate_id}", status_code=201)
def add_from_pool(job_id: UUID, candidate_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.create")
    job = _job(db, tenant, job_id)
    cand = db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.id == candidate_id).first()
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    app = automation.add_from_talent_pool(db, tenant, job, cand, actor=current_user.email)
    return {"application_id": str(app.id), "status": app.status, "score": float(app.composite_score) if app.composite_score is not None else None}


@router.get("/jobs-health")
def jobs_health(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.view")
    return automation.job_health(db, tenant)


@router.get("/candidates/{candidate_id}/duplicates")
def duplicates(candidate_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.candidate.view")
    cand = db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.id == candidate_id).first()
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    found = []
    if cand.duplicate_of_id:
        other = db.get(Candidate, cand.duplicate_of_id)
        if other:
            found.append({"candidate_id": str(other.id), "name": other.full_name, "email": other.email, "reason": "linked earlier record"})
    other, reason = automation.find_duplicate(db, tenant, email=cand.email, phone=cand.phone, resume_sha256=cand.resume_sha256, exclude_id=cand.id)
    if other is not None and str(other.id) not in {f["candidate_id"] for f in found}:
        found.append({"candidate_id": str(other.id), "name": other.full_name, "email": other.email, "reason": reason})
    return {"candidate_id": str(cand.id), "duplicates": found}


@router.get("/system-health")
def system_health(fresh: bool = False, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Part 17.13: database, mailbox, AI, storage, background jobs -- green / amber / red."""
    from app.experience.system_health import check

    tenant = require_current_tenant()
    _need(db, tenant, current_user, "platform.settings.view")
    return check(db, tenant, fresh=fresh)


@router.post("/reminders/run")
def run_reminders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "platform.settings.configure")
    return automation.send_reminders(db, tenant)


@router.get("/applications/{application_id}/status-link")
def status_link(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    app = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.id == application_id).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"url": automation.status_link(db, tenant, app)}


@public_router.get("/{token}")
def public_status(token: str, db: Session = Depends(get_db)):
    from app.models.iam import ActionToken

    tenant = require_current_tenant()
    from datetime import datetime, timezone

    row = db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.token == token, ActionToken.action == automation.STATUS_ACTION).first()
    if row is None or row.invalidated_at is not None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="This link isn't valid any more.")
    app = db.get(Application, row.entity_id)
    if app is None:
        raise HTTPException(status_code=404, detail="This link isn't valid any more.")
    return automation.status_view(db, tenant, app)
