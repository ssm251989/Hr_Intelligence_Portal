from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.integrations.hr_email import get_hr_integration, is_smtp_configured, send_hr_email, SmtpError
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User


def validate_status_transition(current_status: str, new_status: str) -> None:
    """Guards only the transitions that touch 'on_hold' -- every other status pairing
    (draft/ready_for_publishing/published/closed among themselves) keeps its existing,
    unrestricted behavior; that predates this status and isn't part of this change.

    Raises ValueError (callers map this to HTTP 400) with a message naming the specific
    rule that was violated.
    """
    if current_status == new_status:
        return
    if new_status == "on_hold":
        if current_status != "published":
            raise ValueError(
                f"A job can only be put on hold from 'published', not '{current_status}'."
            )
        return
    if current_status == "on_hold":
        if new_status not in ("published", "closed"):
            raise ValueError(
                f"An on-hold job can only resume to 'published' or move to 'closed', not '{new_status}'."
            )
        return


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
    job.closed_at = job.closed_at or datetime.now(timezone.utc)  # Part 21.1: the Recycle-bin countdown starts here
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


def hold_job(db: Session, job: JobRole) -> None:
    """published -> on_hold. Raises ValueError if the job isn't currently published."""
    validate_status_transition(job.status, "on_hold")
    previous_status = job.status
    job.status = "on_hold"
    db.commit()
    db.refresh(job)
    log_action(
        db, "job_role", job.id, "job_put_on_hold", "system",
        {"previous_status": previous_status, "new_status": "on_hold"},
    )


def resume_job(db: Session, job: JobRole) -> None:
    """on_hold -> published. Raises ValueError if the job isn't currently on hold.

    Doesn't rely on validate_status_transition alone: that function only restricts
    transitions that touch 'on_hold' on *either* side, so on its own it would let
    resume_job "resume" a job from any non-on_hold status straight to published (since
    neither side of e.g. draft -> published touches on_hold, that pairing is
    unrestricted by design). "Resume" specifically only makes sense starting from
    on_hold, so that precondition is checked explicitly here.
    """
    if job.status != "on_hold":
        raise ValueError(f"Only an on-hold job can be resumed, not '{job.status}'.")
    validate_status_transition(job.status, "published")
    previous_status = job.status
    job.status = "published"
    db.commit()
    db.refresh(job)
    log_action(
        db, "job_role", job.id, "job_resumed_from_hold", "system",
        {"previous_status": previous_status, "new_status": "published"},
    )


def notify_job_owner_of_new_application(db: Session, job: JobRole, candidate: Candidate) -> None:
    """Best-effort real email to the publishing recruiter when a new application comes in,
    sent from the shared, org-level HR mailbox (app/integrations/hr_email.py) over SMTP --
    not the job owner's own connection, which is no longer relevant to sending at all,
    only to knowing who the recipient is.

    Only fires when the job has "Email notifications" enabled (job.publish_settings) AND
    the HR mailbox's SMTP settings are configured. Sends to job.created_by's own inbox as a
    simple demo/test case, not to the candidate. Never raises -- a missing/broken HR mailbox
    configuration must not block application creation, same treatment as the Calendar/
    DocuSign integrations elsewhere in this app.
    """
    if not (job.publish_settings or {}).get("email_notifications"):
        return
    if not job.created_by:
        return

    user = db.get(User, job.created_by)
    if not user or not user.email:
        return

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        log_action(
            db, "job_role", job.id, "new_application_email_skipped", "system",
            {"reason": "HR mailbox's SMTP settings are not configured", "candidate_id": str(candidate.id)},
        )
        return

    try:
        send_hr_email(
            hr_integration,
            to=user.email,
            subject=f"New application for {job.title}",
            body=(
                f"{candidate.full_name or 'A candidate'} just applied for {job.title}.\n\n"
                "This is a demo notification sent to your own inbox via the shared HR mailbox."
            ),
        )
        log_action(
            db, "job_role", job.id, "new_application_email_sent", "system",
            {"to": user.email, "candidate_id": str(candidate.id)},
        )
    except SmtpError as exc:
        log_action(
            db, "job_role", job.id, "new_application_email_failed", "system",
            {"error": str(exc), "candidate_id": str(candidate.id)},
        )
