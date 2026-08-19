"""Interview Scheduling automation -- selects an available interviewer for a candidate's
preferred time slot from the Excel tracker's Interviewer Pool, checking each candidate
interviewer's REAL Google Calendar in turn until one is found free (or every eligible
interviewer is exhausted). This module itself never sends anything and never creates a real
calendar event -- it only picks a candidate interviewer for one slot; sending the candidate
a confirmation link and creating the real event once they confirm is Part 3's job (see
app/interview_scheduling/confirmation.py). Part 3 emails the candidate directly with a
secure single-use link per proposed slot -- an earlier plan to confirm over WhatsApp/Twilio
was dropped before any of that was built, in favor of email, which this app already had a
real integration for (see app/integrations/gmail.py).

"Busy" and "unknown availability" are treated identically for retry purposes (both mean
"try someone else"), but are logged and reported distinctly: a genuine calendar conflict is
a different, more informative outcome than "this person hasn't connected Google Calendar so
we simply can't tell." Neither is ever treated as "assume free" -- that would risk a real
double-booking once Stage 2 actually creates the calendar event.
"""

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.crypto import decrypt
from app.integrations.google_calendar import (
    DEFAULT_INTERVIEW_DURATION_MINUTES,
    GoogleCalendarError,
    check_calendar_availability,
)
from app.interview_scheduling.tracker import append_interview_log_row, eligible_interviewers_for_job
from app.models.user import User
from app.models.user_integration import UserIntegration

NOT_REGISTERED = "skipped_not_registered"
UNKNOWN_AVAILABILITY = "skipped_unknown_availability"
BUSY = "skipped_busy"
PICKED = "picked"

NO_POOL_CONFIGURED = "No eligible interviewers configured for this job"
ALL_UNAVAILABLE = "All eligible interviewers are busy or have unknown availability"


def _find_interviewer_user(db: Session, name: str) -> Optional[User]:
    """Matches an Interviewer Pool name to exactly one real User by full_name (case/
    whitespace-normalized). Zero or more-than-one match both return None -- an Excel name
    that doesn't map cleanly to one registered account is treated as "can't check this
    person's calendar," never guessed at."""
    name_norm = name.strip().lower()
    matches = [user for user in db.query(User).all() if (user.full_name or "").strip().lower() == name_norm]
    return matches[0] if len(matches) == 1 else None


def _google_integration(db: Session, user: User) -> Optional[UserIntegration]:
    return (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "google")
        .first()
    )


def select_interviewer(
    db: Session,
    tracker_path: str,
    *,
    candidate_name: str,
    job_title: str,
    preferred_time: datetime,
    duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    actor: str = "system",
) -> dict:
    """Picks a random eligible interviewer for `job_title`, checks their real Google
    Calendar for a conflict at `preferred_time`, and retries a different random interviewer
    on conflict/unknown-availability until one is free or the pool is exhausted. Every
    attempt is logged to audit_log (entity_type "interview_scheduling_run", one row per
    attempt plus a final summary) and the outcome is recorded as a new row in the tracker's
    Interview Log sheet -- this function itself never creates a calendar event or sends
    anything.
    """
    run_id = uuid.uuid4()
    eligible = eligible_interviewers_for_job(Path(tracker_path), job_title)

    if not eligible:
        log_action(
            db, "interview_scheduling_run", run_id, "interview_scheduling_run_completed", actor,
            {
                "job_title": job_title, "candidate_name": candidate_name,
                "assigned_interviewer": None, "attempts": [], "reason": NO_POOL_CONFIGURED,
            },
        )
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate_name, "Job Title": job_title,
                "Candidate Preferred Time": preferred_time.isoformat(), "Status": "No Interviewer Available",
            },
        )
        return {
            "run_id": str(run_id), "assigned_interviewer": None, "assigned_interviewer_user_id": None,
            "attempts": [], "reason": NO_POOL_CONFIGURED,
        }

    order = list(eligible)
    random.shuffle(order)
    end_time = preferred_time + timedelta(minutes=duration_minutes)
    attempts: list[dict] = []

    def _record(name: str, outcome: str, reason: str, user: Optional[User] = None) -> None:
        attempt = {"interviewer": name, "outcome": outcome, "reason": reason}
        attempts.append(attempt)
        details = dict(attempt)
        if user is not None:
            details["user_id"] = str(user.id)
        log_action(db, "interview_scheduling_run", run_id, "interview_scheduling_attempt", actor, details)

    for name in order:
        user = _find_interviewer_user(db, name)
        if user is None:
            _record(name, NOT_REGISTERED, f"'{name}' is not a registered user in the system")
            continue

        integration = _google_integration(db, user)
        if integration is None:
            _record(name, UNKNOWN_AVAILABILITY, f"{name} has not connected Google Calendar -- availability unknown", user)
            continue

        try:
            available = check_calendar_availability(decrypt(integration.refresh_token), preferred_time, end_time)
        except (GoogleCalendarError, InvalidToken) as exc:
            _record(name, UNKNOWN_AVAILABILITY, f"Could not check {name}'s calendar: {exc}", user)
            continue

        if not available:
            _record(name, BUSY, f"{name} is busy at {preferred_time.isoformat()}", user)
            continue

        _record(name, PICKED, f"{name} is free at {preferred_time.isoformat()}", user)
        log_action(
            db, "interview_scheduling_run", run_id, "interview_scheduling_run_completed", actor,
            {
                "job_title": job_title, "candidate_name": candidate_name,
                "assigned_interviewer": name, "attempts": attempts, "reason": None,
            },
        )
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate_name, "Job Title": job_title, "Assigned Interviewer": name,
                "Candidate Preferred Time": preferred_time.isoformat(),
                "Status": "Interviewer Selected -- Awaiting Confirmation",
            },
        )
        return {
            "run_id": str(run_id),
            "assigned_interviewer": name,
            # Resolved once here rather than making Part 3 re-run the same name->User lookup
            # (see _find_interviewer_user) a second time against a possibly-changed User
            # table -- the id that actually did the availability check is what a
            # confirmation later creates the calendar event for.
            "assigned_interviewer_user_id": str(user.id),
            "attempts": attempts,
            "reason": None,
        }

    # Every eligible interviewer was tried and none was pickable -- reported clearly, never
    # guessed at or silently left unresolved.
    log_action(
        db, "interview_scheduling_run", run_id, "interview_scheduling_run_completed", actor,
        {
            "job_title": job_title, "candidate_name": candidate_name,
            "assigned_interviewer": None, "attempts": attempts, "reason": ALL_UNAVAILABLE,
        },
    )
    append_interview_log_row(
        Path(tracker_path),
        {
            "Candidate": candidate_name, "Job Title": job_title,
            "Candidate Preferred Time": preferred_time.isoformat(), "Status": "No Interviewer Available",
        },
    )
    return {
        "run_id": str(run_id), "assigned_interviewer": None, "assigned_interviewer_user_id": None,
        "attempts": attempts, "reason": ALL_UNAVAILABLE,
    }
