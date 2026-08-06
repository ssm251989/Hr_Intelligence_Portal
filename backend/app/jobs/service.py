from datetime import date

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.crypto import decrypt
from app.integrations.gmail import GmailError, send_email
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration


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


def notify_job_owner_of_new_application(db: Session, job: JobRole, candidate: Candidate) -> None:
    """Best-effort real email to the publishing recruiter when a new application comes in.

    Only fires when the job has "Email notifications" enabled (job.publish_settings)
    AND the user who created/published it (job.created_by) has Google connected. Sends
    to that user's own inbox as a simple demo/test case, not to the candidate. Never
    raises -- a missing connection, an old token without the gmail.send scope, or any
    Gmail API failure must not block application creation, same treatment as the
    Calendar/DocuSign integrations elsewhere in this app.
    """
    if not (job.publish_settings or {}).get("email_notifications"):
        return
    if not job.created_by:
        return

    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == job.created_by, UserIntegration.provider == "google")
        .first()
    )
    if not integration:
        return

    user = db.get(User, job.created_by)
    if not user or not user.email:
        return

    try:
        send_email(
            decrypt(integration.refresh_token),
            to=user.email,
            subject=f"New application for {job.title}",
            body=(
                f"{candidate.full_name or 'A candidate'} just applied for {job.title}.\n\n"
                "This is a demo notification sent to your own inbox via your connected Google account."
            ),
        )
        log_action(
            db, "job_role", job.id, "new_application_email_sent", "system",
            {"to": user.email, "candidate_id": str(candidate.id)},
        )
    except (GmailError, InvalidToken) as exc:
        error = str(exc) or "Stored Google refresh token could not be decrypted"
        log_action(
            db, "job_role", job.id, "new_application_email_failed", "system",
            {"error": error, "candidate_id": str(candidate.id)},
        )
