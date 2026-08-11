import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.database import get_db
from app.models.application import Application
from app.models.user import User
from app.schemas.application import ApplicationRead, ShortlistDecisionRequest

router = APIRouter(tags=["shortlisting"])


@router.get("/jobs/{job_id}/shortlist", response_model=list[ApplicationRead])
def list_shortlist(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Application)
        .filter(Application.job_role_id == job_id, Application.status == "screened")
        .order_by(Application.match_score.desc())
        .all()
    )


@router.post("/applications/{application_id}/shortlist-decision", response_model=ApplicationRead)
def make_shortlist_decision(
    application_id: uuid.UUID,
    payload: ShortlistDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_not_on_hold(application)
    if application.status != "screened":
        raise HTTPException(
            status_code=400,
            detail="Application must be screened before a shortlisting decision can be made",
        )

    previous_status = application.status
    new_status = "hr_selected" if payload.decision == "select" else "hr_rejected"
    application.status = new_status
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "hr_shortlisting_decision",
        payload.decided_by or current_user.email,
        {
            "decision": payload.decision,
            "notes": payload.notes,
            "previous_status": previous_status,
            "new_status": new_status,
            "match_score": float(application.match_score) if application.match_score is not None else None,
        },
    )
    return application
