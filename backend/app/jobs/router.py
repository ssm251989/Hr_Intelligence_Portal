import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.jd_generator import JDGenerationError, generate_jd
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.jobs.service import close_job_if_deadline_passed
from app.models.job_role import JobRole
from app.models.user import User
from app.schemas.job import JobRoleCreate, JobRoleRead, JobRoleUpdate, PublishPlatformsRequest

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_job_or_404(db: Session, job_id: uuid.UUID) -> JobRole:
    job = db.get(JobRole, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job role not found")
    return job


def _render_jd_text(jd: dict) -> str:
    sections = [
        jd["title"],
        "",
        jd["summary"],
        "",
        "Responsibilities:",
        *[f"- {item}" for item in jd["responsibilities"]],
        "",
        "Required skills:",
        *[f"- {item}" for item in jd["required_skills"]],
        "",
        "Nice to have:",
        *[f"- {item}" for item in jd["nice_to_have"]],
        "",
        f"Experience required: {jd['experience_required']}",
    ]
    return "\n".join(sections)


@router.post("", response_model=JobRoleRead, status_code=201)
def create_job(
    payload: JobRoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    data = payload.model_dump()
    # Always the authenticated caller, never client-supplied -- this is who "the
    # publishing user" means for the email_notifications feature (see
    # app/jobs/service.py notify_job_owner_of_new_application), so it must be
    # trustworthy rather than whatever a client happens to send.
    data["created_by"] = current_user.id
    job = JobRole(**data)
    db.add(job)
    db.commit()
    db.refresh(job)
    log_action(db, "job_role", job.id, "job_role_created", "system", {"status": job.status})
    return job


@router.get("", response_model=list[JobRoleRead])
def list_jobs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    jobs = db.query(JobRole).order_by(JobRole.created_at.desc()).all()
    for job in jobs:
        close_job_if_deadline_passed(db, job)
    return jobs


@router.get("/{job_id}", response_model=JobRoleRead)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    close_job_if_deadline_passed(db, job)
    return job


@router.patch("/{job_id}", response_model=JobRoleRead)
def update_job(
    job_id: uuid.UUID,
    payload: JobRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    job = _get_job_or_404(db, job_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    log_action(db, "job_role", job.id, "job_role_updated", "system", updates)
    return job


@router.post("/{job_id}/generate-jd", response_model=JobRoleRead)
def generate_job_description(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    job = _get_job_or_404(db, job_id)
    try:
        result = generate_jd(
            {
                "title": job.title,
                "department": job.department,
                "location": job.location,
                "experience_level": job.experience_level,
                "skills": job.skills,
                "salary_band_min": job.salary_band_min,
                "salary_band_max": job.salary_band_max,
            }
        )
    except JDGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log_action(db, "job_role", job.id, "ai_jd_generator_scored", "system", result)
    job.jd_text = _render_jd_text(result)
    job.status = "ready_for_publishing"
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/publish", response_model=JobRoleRead)
def publish_job_platforms(
    job_id: uuid.UUID,
    payload: PublishPlatformsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    """Final step of the create-job wizard.

    Naukri.com and LinkedIn have no real posting API access (no business
    partnership) -- checking those boxes only records intent below, it never
    calls out to either site. Only "career_portal" is real: it's the one
    flag that flips job_roles.status, which is what makes the job appear on
    GET /public/jobs and /careers.
    """
    job = _get_job_or_404(db, job_id)
    previous_status = job.status

    job.published_platforms = {
        "naukri": payload.naukri,
        "linkedin": payload.linkedin,
        "career_portal": payload.career_portal,
    }
    job.publish_settings = {
        "email_notifications": payload.email_notifications,
        "application_deadline": (
            payload.application_deadline.isoformat() if payload.application_deadline else None
        ),
    }
    if payload.posting_url_naukri is not None:
        job.posting_url_naukri = payload.posting_url_naukri or None
    if payload.posting_url_linkedin is not None:
        job.posting_url_linkedin = payload.posting_url_linkedin or None
    job.status = "published" if payload.career_portal else "ready_for_publishing"
    db.commit()
    db.refresh(job)

    log_action(
        db,
        "job_role",
        job.id,
        "job_platforms_published",
        "system",
        {
            "previous_status": previous_status,
            "new_status": job.status,
            "published_platforms": job.published_platforms,
        },
    )
    return job
