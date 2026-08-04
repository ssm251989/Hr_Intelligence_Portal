import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.jd_generator import generate_jd
from app.audit.service import log_action
from app.core.database import get_db
from app.models.job_role import JobRole
from app.schemas.job import JobRoleCreate, JobRoleRead, JobRoleUpdate

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
def create_job(payload: JobRoleCreate, db: Session = Depends(get_db)):
    job = JobRole(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    log_action(db, "job_role", job.id, "job_role_created", "system", {"status": job.status})
    return job


@router.get("", response_model=list[JobRoleRead])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(JobRole).order_by(JobRole.created_at.desc()).all()


@router.get("/{job_id}", response_model=JobRoleRead)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_job_or_404(db, job_id)


@router.patch("/{job_id}", response_model=JobRoleRead)
def update_job(job_id: uuid.UUID, payload: JobRoleUpdate, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    log_action(db, "job_role", job.id, "job_role_updated", "system", updates)
    return job


@router.post("/{job_id}/generate-jd", response_model=JobRoleRead)
def generate_job_description(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
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
    log_action(db, "job_role", job.id, "ai_jd_generator_scored", "system", result)
    job.jd_text = _render_jd_text(result)
    job.status = "ready_for_publishing"
    db.commit()
    db.refresh(job)
    return job
