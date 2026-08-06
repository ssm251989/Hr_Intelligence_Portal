from datetime import date

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.job_role import JobRole


def get_application_deadline(job: JobRole) -> date | None:
    raw = (job.publish_settings or {}).get("application_deadline")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def close_job_if_deadline_passed(db: Session, job: JobRole) -> bool:
    """Lazily enforce a job's application deadline.

    There's no scheduler/cron in this app, so instead of a background job this
    is called on every read (GET /jobs, GET /jobs/{id}, and their /public
    equivalents) and flips a published job to 'closed' the first time anyone
    reads it after its deadline has passed. Returns True if this call just
    closed it.
    """
    if job.status != "published":
        return False
    deadline = get_application_deadline(job)
    if deadline is None or deadline >= date.today():
        return False

    previous_status = job.status
    job.status = "closed"
    db.commit()
    db.refresh(job)
    log_action(
        db,
        "job_role",
        job.id,
        "job_auto_closed_deadline_passed",
        "system",
        {"previous_status": previous_status, "application_deadline": deadline.isoformat()},
    )
    return True
