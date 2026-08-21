"""Part 3: candidate email + secure-link interview confirmation.

An earlier plan had the candidate confirm a slot over WhatsApp once real Twilio credentials
existed; that was dropped before any of it was built, in favor of emailing the candidate
directly via the shared HR mailbox's SMTP integration (app/integrations/hr_email.py) with a
secure, single-use link per proposed slot -- no new third-party integration needed.

Flow:
  1. propose_interview_slots runs the existing single-slot interviewer-selection logic
     (service.select_interviewer) once per candidate-facing slot option, keeps whichever
     slots actually found someone free, and emails the candidate one distinct
     /interview-confirm/{token} link per kept slot.
  2. The candidate clicks one. confirm_token validates that token (real, unexpired, unused),
     and if valid: records the chosen slot, creates a REAL Google Calendar event, advances
     the application to interview_scheduled, invalidates the other slots' tokens, and
     updates that slot's Interview Log row with the final outcome.

Nothing here ever guesses at an outcome it can't verify -- an expired/used/unrecognized
token gets a plain, honest answer, never a raw error and never a silent "probably fine".
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.crypto import decrypt
from app.core.config import settings
from app.integrations.hr_email import send_hr_email
from app.integrations.google_calendar import (
    APP_TIMEZONE,
    DEFAULT_INTERVIEW_DURATION_MINUTES,
    GoogleCalendarError,
    create_calendar_event,
    format_ist_datetime,
)
from app.interview_scheduling.service import select_interviewer
from app.interview_scheduling.tracker import sync_interviewer_pool_job_titles, update_interview_log_row
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.interview_confirmation_token import InterviewConfirmationToken
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration

# Links stay confirmable for 5 days after being emailed -- long enough for a candidate to
# respond without leaving a slot proposal "live" indefinitely.
TOKEN_EXPIRY_DAYS = 5

SLOTS_TO_PROPOSE = 3
# There's no candidate time-preference input anywhere in this app yet, so the 3 slots
# offered are simply the next 3 business days (Mon-Fri) at a fixed mid-morning hour --
# a plain, easy-to-explain placeholder, not an attempt to be smart about anyone's real
# calendar. A recruiter who needs a different time can still use the existing manual
# scheduling flow (POST /applications/{id}/interviews) instead.
DEFAULT_SLOT_HOUR_IST = time(10, 0)


@dataclass
class ConfirmationOutcome:
    status: str  # "confirmed" | "invalid" | "used" | "invalidated" | "expired"
    message: str
    candidate_name: Optional[str] = None
    job_title: Optional[str] = None
    interviewer_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    calendar_link: Optional[str] = None


def _next_business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:  # Monday=0 .. Friday=4
            days.append(current)
        current += timedelta(days=1)
    return days


def default_proposed_slot_times(now: Optional[datetime] = None) -> list[datetime]:
    """The next SLOTS_TO_PROPOSE business days (starting tomorrow, so a candidate always
    gets real notice) at DEFAULT_SLOT_HOUR_IST, returned as UTC-aware datetimes."""
    now = now or datetime.now(timezone.utc)
    today_ist = now.astimezone(APP_TIMEZONE).date()
    business_days = _next_business_days(today_ist + timedelta(days=1), SLOTS_TO_PROPOSE)
    return [
        datetime.combine(day, DEFAULT_SLOT_HOUR_IST, tzinfo=APP_TIMEZONE).astimezone(timezone.utc)
        for day in business_days
    ]


def _build_proposal_email_body(candidate_name: str, job_title: str, offered: list[dict]) -> str:
    options = "\n\n".join(
        f"Option {i}: {format_ist_datetime(slot['slot_time'])}\nConfirm this slot: {slot['url']}"
        for i, slot in enumerate(offered, start=1)
    )
    return (
        f"Hi {candidate_name or 'there'},\n\n"
        f"We'd like to schedule your interview for the {job_title} position. Please choose "
        "one of the available time slots below by opening its link -- once you confirm one, "
        "the other options stop working.\n\n"
        f"{options}\n\n"
        f"These links expire in {TOKEN_EXPIRY_DAYS} days. If none of these times work for "
        "you, just reply to this email and we'll find another time.\n\n"
        "Thanks!"
    )


def propose_interview_slots(
    db: Session,
    application: Application,
    *,
    tracker_path: str,
    candidate: Candidate,
    job: JobRole,
    hr_integration,
    actor: str,
    now: Optional[datetime] = None,
) -> dict:
    """Emails the candidate up to SLOTS_TO_PROPOSE distinct confirmation links, one per slot
    a real interviewer was actually found free for -- a slot nobody was free for is simply
    dropped, never offered as a link that wouldn't actually work. Returns
    {"slots_offered": int, "tokens": [...]}; sends no email and creates no tokens if zero
    slots could be filled (the caller decides whether that's an error).
    """
    if not candidate.email:
        raise ValueError("Candidate has no email on file")

    now = now or datetime.now(timezone.utc)

    # Interview Scheduling has no scheduler of its own to run sync_interviewer_pool_job_
    # titles on a tick (unlike Part G's local-folder import) -- this is the one recurring
    # moment the Interviewer Pool sheet actually gets read (select_interviewer below), so
    # syncing right here guarantees it's never stale when it matters, same as the settings-
    # save action (see app/interview_scheduling/router.py update_settings).
    sync_interviewer_pool_job_titles(db, Path(tracker_path))

    # A fresh proposal supersedes any still-live one, so a recruiter re-running this can't
    # leave two conflicting sets of links both confirmable at once.
    stale_tokens = (
        db.query(InterviewConfirmationToken)
        .filter(
            InterviewConfirmationToken.application_id == application.id,
            InterviewConfirmationToken.used_at.is_(None),
            InterviewConfirmationToken.invalidated_at.is_(None),
        )
        .all()
    )
    for stale_token in stale_tokens:
        stale_token.invalidated_at = now

    expires_at = now + timedelta(days=TOKEN_EXPIRY_DAYS)
    offered: list[dict] = []
    for slot_time in default_proposed_slot_times(now):
        result = select_interviewer(
            db, tracker_path, candidate_name=candidate.full_name, job_title=job.title,
            preferred_time=slot_time, actor=actor,
        )
        if not result["assigned_interviewer"]:
            continue

        interviewer_user_id = result.get("assigned_interviewer_user_id")
        token_row = InterviewConfirmationToken(
            application_id=application.id,
            token=secrets.token_urlsafe(32),
            candidate_name=candidate.full_name,
            job_title=job.title,
            interviewer_name=result["assigned_interviewer"],
            interviewer_user_id=uuid.UUID(interviewer_user_id) if interviewer_user_id else None,
            slot_time=slot_time,
            duration_minutes=DEFAULT_INTERVIEW_DURATION_MINUTES,
            tracker_path=tracker_path,
            expires_at=expires_at,
        )
        db.add(token_row)
        offered.append(
            {
                "token": token_row.token,
                "slot_time": slot_time,
                "interviewer_name": result["assigned_interviewer"],
                "url": f"{settings.APP_BASE_URL}/interview-confirm/{token_row.token}",
            }
        )

    if not offered:
        db.commit()
        return {"slots_offered": 0, "expires_at": expires_at, "tokens": []}

    db.commit()

    send_hr_email(
        hr_integration,
        to=candidate.email,
        subject=f"Interview scheduling for {job.title}",
        body=_build_proposal_email_body(candidate.full_name, job.title, offered),
    )
    log_action(
        db, "application", application.id, "interview_slots_proposed", actor,
        {"job_title": job.title, "slots_offered": len(offered), "candidate_email": candidate.email},
    )
    return {"slots_offered": len(offered), "expires_at": expires_at, "tokens": offered}


def create_confirmed_calendar_event(db: Session, application: Application, token_row) -> Optional[dict]:
    """Best-effort, like every other Google Calendar call in this app (see
    scheduling/router.py _try_create_calendar_event) -- a missing/broken interviewer
    connection is logged, not raised, so it can never block a confirmation that has already
    been recorded.

    Duck-typed on `token_row` deliberately (not annotated to InterviewConfirmationToken) --
    it only ever reads .interviewer_user_id/.slot_time/.duration_minutes/.job_title, which
    app.models.negotiation_token.NegotiationToken's rows carry too, so the interviewer-first
    negotiation flow (app/interview_scheduling/negotiation.py) reuses this exact function for
    its own final calendar-event step rather than duplicating it."""
    if token_row.interviewer_user_id is None:
        return None
    interviewer = db.get(User, token_row.interviewer_user_id)
    if interviewer is None:
        return None
    integration = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == interviewer.id, UserIntegration.provider == "google")
        .first()
    )
    if integration is None:
        return None

    candidate = db.get(Candidate, application.candidate_id)
    attendee_emails = [email for email in (candidate.email if candidate else None, interviewer.email) if email]
    try:
        return create_calendar_event(
            decrypt(integration.refresh_token),
            summary=f"Interview: {candidate.full_name if candidate else 'Candidate'} — {token_row.job_title}",
            description=f"Interview confirmed by candidate for application {application.id}.",
            start=token_row.slot_time,
            attendee_emails=attendee_emails,
            duration_minutes=token_row.duration_minutes or DEFAULT_INTERVIEW_DURATION_MINUTES,
        )
    except (GoogleCalendarError, InvalidToken) as exc:
        error = str(exc) or "Stored Google refresh token could not be decrypted"
        log_action(
            db, "application", application.id, "interview_confirmation_calendar_event_failed", "candidate",
            {"interviewer_id": str(interviewer.id), "error": error},
        )
        return None


def confirm_token(db: Session, token: str) -> ConfirmationOutcome:
    """The single entry point behind GET /interview-confirm/{token}. Every branch returns a
    plain, honest ConfirmationOutcome -- never raises for an expired/used/unrecognized
    token, since a candidate clicking a stale email link is an expected outcome, not a bug.
    """
    now = datetime.now(timezone.utc)
    token_row = db.query(InterviewConfirmationToken).filter(InterviewConfirmationToken.token == token).first()

    if token_row is None:
        return ConfirmationOutcome(
            status="invalid",
            message="This confirmation link isn't recognized. Please use the exact link from your email, "
            "or contact the recruiter if you believe this is a mistake.",
        )
    if token_row.used_at is not None:
        return ConfirmationOutcome(
            status="used",
            message="This interview slot has already been confirmed. If you didn't do this yourself, "
            "please contact the recruiter.",
            candidate_name=token_row.candidate_name,
            job_title=token_row.job_title,
            interviewer_name=token_row.interviewer_name,
            scheduled_at=token_row.slot_time,
        )
    if token_row.invalidated_at is not None:
        return ConfirmationOutcome(
            status="invalidated",
            message="This time slot is no longer available -- you already confirmed a different interview "
            "time. Check your email for the confirmation details.",
            candidate_name=token_row.candidate_name,
            job_title=token_row.job_title,
        )
    if token_row.expires_at < now:
        return ConfirmationOutcome(
            status="expired",
            message=f"This confirmation link has expired (links are valid for {TOKEN_EXPIRY_DAYS} days). "
            "Please contact the recruiter to arrange a new time.",
            candidate_name=token_row.candidate_name,
            job_title=token_row.job_title,
        )

    application = db.get(Application, token_row.application_id)
    if application is None:
        return ConfirmationOutcome(
            status="invalid",
            message="This confirmation link no longer refers to a valid application. "
            "Please contact the recruiter.",
        )

    token_row.used_at = now
    previous_status = application.status
    application.status = "interview_scheduled"

    other_tokens = (
        db.query(InterviewConfirmationToken)
        .filter(
            InterviewConfirmationToken.application_id == application.id,
            InterviewConfirmationToken.id != token_row.id,
            InterviewConfirmationToken.used_at.is_(None),
            InterviewConfirmationToken.invalidated_at.is_(None),
        )
        .all()
    )
    for other in other_tokens:
        other.invalidated_at = now

    calendar_event = create_confirmed_calendar_event(db, application, token_row)

    # The manual scheduling flow (app/scheduling/router.py schedule_interview) always
    # creates an Interview row; this flow -- the only other path that can schedule one --
    # must too, or the Interview List/Dashboard (which reads exclusively off the
    # `interviews` table) would silently never see any auto-scheduled interview at all.
    interview = Interview(
        application_id=application.id,
        interviewer_id=token_row.interviewer_user_id,
        scheduled_at=token_row.slot_time,
        calendar_event_id=calendar_event["event_id"] if calendar_event else None,
        calendar_link=calendar_event["html_link"] if calendar_event else None,
        scheduling_method="auto",
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)

    log_action(
        db, "application", application.id, "interview_confirmed_by_candidate", "candidate",
        {
            "previous_status": previous_status, "interviewer_name": token_row.interviewer_name,
            "scheduled_at": token_row.slot_time.isoformat(), "calendar_event_created": calendar_event is not None,
            "other_slots_invalidated": len(other_tokens), "interview_id": str(interview.id),
        },
    )
    log_action(
        db, "interview", interview.id, "interview_scheduled", "candidate",
        {
            "application_id": str(application.id), "scheduled_at": token_row.slot_time.isoformat(),
            "scheduling_method": "auto", "interviewer_name": token_row.interviewer_name,
        },
    )

    if token_row.tracker_path:
        try:
            update_interview_log_row(
                Path(token_row.tracker_path),
                candidate=token_row.candidate_name or "",
                job_title=token_row.job_title or "",
                preferred_time=format_ist_datetime(token_row.slot_time),
                updates={
                    "Interviewer Confirmed": "Yes",
                    "Candidate Confirmed": "Yes",
                    "Final Scheduled Time": format_ist_datetime(token_row.slot_time),
                    "Status": "Confirmed",
                },
            )
        except OSError as exc:
            log_action(
                db, "application", application.id, "interview_log_update_failed", "candidate",
                {"tracker_path": token_row.tracker_path, "error": str(exc)},
            )
        for other in other_tokens:
            try:
                update_interview_log_row(
                    Path(other.tracker_path or token_row.tracker_path),
                    candidate=other.candidate_name or "",
                    job_title=other.job_title or "",
                    preferred_time=format_ist_datetime(other.slot_time),
                    updates={"Status": "Slot Not Selected by Candidate"},
                )
            except OSError:
                pass

    return ConfirmationOutcome(
        status="confirmed",
        message="Your interview is confirmed! We look forward to speaking with you.",
        candidate_name=token_row.candidate_name,
        job_title=token_row.job_title,
        interviewer_name=token_row.interviewer_name,
        scheduled_at=token_row.slot_time,
        calendar_link=calendar_event["html_link"] if calendar_event else None,
    )
