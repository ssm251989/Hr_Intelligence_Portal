import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.models.application import Application
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.application import ApplicationRead
from app.schemas.salary import SalaryApprovalRequest, SalaryStatusResponse

router = APIRouter(prefix="/applications", tags=["salary"])

VALIDATABLE_STATUSES = {"hr_selected", "interview_selected"}


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.post("/{application_id}/validate-salary", response_model=ApplicationRead)
def validate_salary(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status not in VALIDATABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Application must be HR-selected or interview-selected before salary validation",
        )
    if application.expected_salary is None:
        raise HTTPException(status_code=400, detail="Application has no expected salary set")

    job = db.get(JobRole, application.job_role_id)
    if not job or job.salary_band_min is None or job.salary_band_max is None:
        raise HTTPException(status_code=400, detail="Job salary band is not set")

    expected_salary = float(application.expected_salary)
    salary_band_min = float(job.salary_band_min)
    salary_band_max = float(job.salary_band_max)
    within_band = expected_salary <= salary_band_max

    previous_status = application.status
    new_status = "salary_ok" if within_band else "salary_above_band"
    application.status = new_status
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "salary_validated",
        "system",
        {
            "expected_salary": expected_salary,
            "salary_band_min": salary_band_min,
            "salary_band_max": salary_band_max,
            "within_band": within_band,
            "previous_status": previous_status,
            "new_status": new_status,
        },
    )
    return application


@router.post("/{application_id}/salary/confirm", response_model=ApplicationRead)
def confirm_salary(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status != "salary_ok":
        raise HTTPException(
            status_code=400,
            detail="Application must be in salary_ok status to confirm salary",
        )

    previous_status = application.status
    application.approved_salary = application.expected_salary
    application.status = "salary_approved"
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "salary_confirmed",
        current_user.email,
        {
            "approved_salary": float(application.approved_salary) if application.approved_salary is not None else None,
            "previous_status": previous_status,
            "new_status": application.status,
        },
    )
    return application


@router.post("/{application_id}/approve-salary", response_model=ApplicationRead)
def approve_salary(
    application_id: uuid.UUID,
    payload: SalaryApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status != "salary_above_band":
        raise HTTPException(
            status_code=400,
            detail="Application must be in salary_above_band status before an approval decision",
        )

    previous_status = application.status
    final_salary = None

    if payload.decision == "approve":
        final_salary = (
            payload.approved_salary
            if payload.approved_salary is not None
            else float(application.expected_salary)
        )
        application.approved_salary = final_salary
        new_status = "salary_approved"
    else:
        new_status = "salary_rejected"

    application.status = new_status
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "salary_approval_decision",
        payload.approved_by or current_user.email,
        {
            "decision": payload.decision,
            "approved_salary": final_salary,
            "notes": payload.notes,
            "previous_status": previous_status,
            "new_status": new_status,
        },
    )
    return application


@router.get("/{application_id}/salary-status", response_model=SalaryStatusResponse)
def get_salary_status(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    application = _get_application_or_404(db, application_id)
    job = db.get(JobRole, application.job_role_id)

    return SalaryStatusResponse(
        application_id=application.id,
        status=application.status,
        expected_salary=float(application.expected_salary) if application.expected_salary is not None else None,
        approved_salary=float(application.approved_salary) if application.approved_salary is not None else None,
        salary_band_min=float(job.salary_band_min) if job and job.salary_band_min is not None else None,
        salary_band_max=float(job.salary_band_max) if job and job.salary_band_max is not None else None,
    )
