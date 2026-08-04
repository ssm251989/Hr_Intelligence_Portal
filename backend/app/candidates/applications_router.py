import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.schemas.application import ApplicationCreate, ApplicationRead

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=201)
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)):
    if not db.get(JobRole, payload.job_role_id):
        raise HTTPException(status_code=404, detail="Job role not found")
    if not db.get(Candidate, payload.candidate_id):
        raise HTTPException(status_code=404, detail="Candidate not found")

    application = Application(
        job_role_id=payload.job_role_id,
        candidate_id=payload.candidate_id,
        expected_salary=payload.expected_salary,
        status="received",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    log_action(db, "application", application.id, "application_created", "system", {"status": application.status})
    return application


@router.get("", response_model=list[ApplicationRead])
def list_applications(job_role_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Application)
    if job_role_id is not None:
        query = query.filter(Application.job_role_id == job_role_id)
    return query.order_by(Application.created_at.desc()).all()
