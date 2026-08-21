"""Interviewer-first scheduling negotiation -- the flow auto-triggered the moment an
application's status transitions into Shortlisted ('hr_selected'), replacing the
candidate-facing part of the older flow (app/interview_scheduling/confirmation.py
propose_interview_slots) for that one trigger point. The manual "Propose Slots" button
(app/interview_scheduling/router.py propose_slots) is untouched and still uses the older
flow directly.

Flow (see the Interviewer Pool / Interview Log / Mails sheets in the configured Excel
tracker, app/interview_scheduling/tracker.py):
  1. On the Shortlisted transition, look up the candidate's job title in the Interviewer
     Pool sheet for its ordered list of eligible interviewers.
  2. Walk that list in order. Skip anyone tracker.interviewer_busy_this_week() says is
     already busy this week (the Interview Log sheet is the ONLY busy-check source here --
     no real-time Calendar call, unlike the older select_interviewer flow).
  3. The first non-busy interviewer who also has an email in the Mails sheet and resolves
     to exactly one registered, Google-connected User gets emailed 3 slot options for
     "tomorrow" (10AM/3PM/6PM) plus a "None of these work" link and a "Done selecting"
     link, via the negotiation-token variant (app.models.negotiation_token
     .NegotiationToken) that lets clicking more than one slot link mark more than one
     available, unlike InterviewConfirmationToken's single-click-is-final semantics.
  4. "None of these work" (or "Done" with nothing marked) moves on to the next interviewer
     in the pool, for the SAME day.
  5. Once the whole pool is exhausted for a day, retry it once more for the day after --
     tracked by which distinct round_days have actually been tried for this application,
     not by re-deriving "tomorrow" from wall-clock time at whatever moment an interviewer
     happens to respond (which could be days after the negotiation started). If that retry
     also exhausts the pool, the application is flagged for manual scheduling (an Interview
     Log Status row, see _flag_for_manual_scheduling) and nothing further is attempted
     automatically.
  6. Once an interviewer's "Done" link is clicked with 1+ slots marked, the candidate is
     emailed exactly those slots via the SAME multi-select token variant, adapted for the
     candidate ("reuse/adapt the existing candidate-facing email", per spec).
  7. Once the candidate's "Done" link is clicked with 1+ slots marked, the EARLIEST one is
     picked, a real Google Calendar event is created (reusing
     confirmation.create_confirmed_calendar_event unchanged, duck-typed against
     NegotiationToken), application.status becomes 'interview_scheduled', an Interview row
     is created, and every other outstanding token for the application is invalidated.

Idempotency: attempt_auto_negotiate_interview_slots below is the only entry point, called
right after the Shortlisted transition itself (never a periodic sweep, see its own
docstring) -- it refuses to start a second negotiation for an application that already has
a live token batch, a scheduled Interview, or an already-logged manual-scheduling flag.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.config import settings
from app.integrations.google_calendar import APP_TIMEZONE, format_ist_datetime
from app.integrations.hr_email import get_hr_integration, is_smtp_configured, send_hr_email, SmtpError
from app.interview_scheduling.confirmation import create_confirmed_calendar_event
from app.interview_scheduling.service import _find_interviewer_user, _google_integration
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.interview_scheduling.tracker import (
    append_interview_log_row,
    eligible_interviewers_for_job,
    email_for_interviewer,
    interviewer_busy_this_week,
    sync_interviewer_pool_job_titles,
)
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.negotiation_token import NegotiationToken
from app.models.user import User

# Slot options offered for one negotiated day -- fixed, not derived from any candidate
# time-preference input (this app has none), per spec.
SLOT_HOURS_IST = (time(10, 0), time(15, 0), time(18, 0))

# Same window InterviewConfirmationToken already uses for its own links -- no reason for a
# different lifetime for this flow's own links.
TOKEN_EXPIRY_DAYS = 5

_SKIP_ACTION = "interview_negotiation_skipped"
_ATTEMPT_ACTION = "interview_negotiation_interviewer_attempt"
_MANUAL_ACTION = "interview_negotiation_manual_scheduling_required"


def _skip(db: Session, application: Application, actor_email: str, reason: str) -> None:
    log_action(db, "application", application.id, _SKIP_ACTION, actor_email, {"reason": reason})


def _tomorrow_ist(now: datetime) -> date:
    return (now.astimezone(APP_TIMEZONE) + timedelta(days=1)).date()


def _slot_times_for_day(day: date) -> list[datetime]:
    return [datetime.combine(day, hour, tzinfo=APP_TIMEZONE).astimezone(timezone.utc) for hour in SLOT_HOURS_IST]


def _format_slot(slot_time: datetime) -> str:
    return format_ist_datetime(slot_time)


def _has_live_negotiation_or_scheduled_interview(db: Session, application: Application, now: Optional[datetime] = None) -> bool:
    """True if this application already has a live (not yet invalidated/expired)
    negotiation-token batch, an existing Interview row (scheduled through this flow, the
    older flow, or the fully-manual endpoint), or has already been flagged for manual
    scheduling -- any of which means attempt_auto_negotiate_interview_slots must not start
    a second, overlapping negotiation."""
    now = now or datetime.now(timezone.utc)
    live_token = (
        db.query(NegotiationToken)
        .filter(
            NegotiationToken.application_id == application.id,
            NegotiationToken.invalidated_at.is_(None),
            NegotiationToken.expires_at > now,
        )
        .first()
    )
    if live_token is not None:
        return True
    if db.query(Interview).filter(Interview.application_id == application.id).first() is not None:
        return True
    flagged = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == _MANUAL_ACTION)
        .first()
    )
    return flagged is not None


def _distinct_interviewer_round_days(db: Session, application: Application) -> list[date]:
    rows = (
        db.query(NegotiationToken.round_day)
        .filter(NegotiationToken.application_id == application.id, NegotiationToken.role == "interviewer")
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows})


def _already_attempted_names(db: Session, application: Application, round_day: date) -> set[str]:
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == _ATTEMPT_ACTION)
        .all()
    )
    return {
        entry.details["interviewer"].strip().lower()
        for entry in entries
        if entry.details.get("round_day") == round_day.isoformat()
    }


def _log_attempt(db: Session, application: Application, actor_email: str, name: str, round_day: date, outcome: str) -> None:
    log_action(
        db, "application", application.id, _ATTEMPT_ACTION, actor_email,
        {"interviewer": name, "round_day": round_day.isoformat(), "outcome": outcome},
    )


def _build_interviewer_email_body(
    candidate_name: str, job_title: str, round_day: date, slot_links: list[dict], not_available_url: str, done_url: str
) -> str:
    options = "\n".join(f"- {link['label']}: {link['url']}" for link in slot_links)
    return (
        f"Hi,\n\n"
        f"We'd like you to interview {candidate_name or 'a candidate'} for the {job_title} role, "
        f"on {round_day.strftime('%d %b %Y')}. Please click every time below that works for you:\n\n"
        f"{options}\n\n"
        f"Once you've marked everything that works, click this link so we can notify the candidate:\n"
        f"Done selecting -- notify candidate now: {done_url}\n\n"
        f"If none of these times work for you, click here instead:\n"
        f"None of these work for me: {not_available_url}\n\n"
        f"These links expire in {TOKEN_EXPIRY_DAYS} days.\n\nThanks!"
    )


def _build_candidate_email_body(candidate_name: str, job_title: str, slot_links: list[dict], not_available_url: str, done_url: str) -> str:
    options = "\n".join(f"- {link['label']}: {link['url']}" for link in slot_links)
    return (
        f"Hi {candidate_name or 'there'},\n\n"
        f"We'd like to schedule your interview for the {job_title} position. Please click every time "
        f"below that works for you:\n\n"
        f"{options}\n\n"
        f"Once you've marked everything that works, click this link to confirm:\n"
        f"Done selecting -- confirm now: {done_url}\n\n"
        f"If none of these times work for you, click here instead:\n"
        f"None of these work for me: {not_available_url}\n\n"
        f"These links expire in {TOKEN_EXPIRY_DAYS} days. Thanks!"
    )


def _token_url(token: str) -> str:
    return f"{settings.APP_BASE_URL}/interview-negotiation/{token}"


def _create_batch(
    db: Session,
    *,
    application: Application,
    role: str,
    interviewer_user_id,
    actor_email: str,
    candidate_name: Optional[str],
    job_title: Optional[str],
    interviewer_name: Optional[str],
    round_day: date,
    slot_times: list[datetime],
    tracker_path: str,
    now: Optional[datetime] = None,
) -> list[NegotiationToken]:
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TOKEN_EXPIRY_DAYS)
    rows = []
    for slot_time in slot_times:
        rows.append(
            NegotiationToken(
                application_id=application.id, role=role, interviewer_user_id=interviewer_user_id,
                actor_email=actor_email, candidate_name=candidate_name, job_title=job_title,
                interviewer_name=interviewer_name, round_day=round_day, kind="slot", slot_time=slot_time,
                tracker_path=str(tracker_path), token=secrets.token_urlsafe(32), expires_at=expires_at,
            )
        )
    for kind in ("not_available", "done"):
        rows.append(
            NegotiationToken(
                application_id=application.id, role=role, interviewer_user_id=interviewer_user_id,
                actor_email=actor_email, candidate_name=candidate_name, job_title=job_title,
                interviewer_name=interviewer_name, round_day=round_day, kind=kind, slot_time=None,
                tracker_path=str(tracker_path), token=secrets.token_urlsafe(32), expires_at=expires_at,
            )
        )
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _invalidate_batch(db: Session, rows: list[NegotiationToken], now: Optional[datetime] = None) -> None:
    """_create_batch above already committed these rows before the caller ever attempts to
    send the corresponding email -- if that send then fails, the batch must not survive as
    live, or _has_live_negotiation_or_scheduled_interview's idempotency guard blocks every
    retry of this application for up to TOKEN_EXPIRY_DAYS even after the send issue itself
    is fixed (the exact orphaned-token incident this exists to prevent)."""
    now = now or datetime.now(timezone.utc)
    for row in rows:
        row.invalidated_at = now
    db.commit()


def _slot_links(rows: list[NegotiationToken]) -> list[dict]:
    return [
        {"label": _format_slot(row.slot_time), "url": _token_url(row.token)}
        for row in rows
        if row.kind == "slot"
    ]


def _flag_for_manual_scheduling(db: Session, application: Application, tracker_path: str, candidate: Candidate, job: JobRole, actor_email: str) -> None:
    append_interview_log_row(
        Path(tracker_path),
        {"Candidate": candidate.full_name or "", "Job Title": job.title, "Status": "Manual Scheduling Required"},
    )
    log_action(
        db, "application", application.id, _MANUAL_ACTION, actor_email,
        {"job_title": job.title, "candidate_name": candidate.full_name},
    )


def _advance_interviewer_round(
    db: Session, application: Application, candidate: Candidate, job: JobRole, tracker_path: str,
    round_day: date, actor_user: User, hr_integration,
) -> str:
    """Walks the job's Interviewer Pool, in order, for `round_day`, skipping anyone already
    attempted for this exact (application, round_day) pair (see _already_attempted_names --
    derived from audit_log, not a separate counter, so this is safely re-callable any number
    of times as interviewers respond asynchronously), busy this week, missing a Mails-sheet
    email, or not resolving to a registered Google-connected User. Starts a batch for and
    emails the first interviewer who clears every check, returning "started"; returns
    "exhausted" once the whole pool has been walked with nobody clearing them all.
    """
    pool = eligible_interviewers_for_job(Path(tracker_path), job.title)

    tried = _already_attempted_names(db, application, round_day)
    for name in pool:
        name_key = name.strip().lower()
        if name_key in tried:
            continue
        if interviewer_busy_this_week(Path(tracker_path), name):
            _log_attempt(db, application, actor_user.email, name, round_day, "busy_this_week")
            continue
        email = email_for_interviewer(Path(tracker_path), name)
        if not email:
            _log_attempt(db, application, actor_user.email, name, round_day, "no_email_on_file")
            continue
        interviewer_user = _find_interviewer_user(db, name)
        if interviewer_user is None:
            _log_attempt(db, application, actor_user.email, name, round_day, "not_a_registered_user")
            continue
        if _google_integration(db, interviewer_user) is None:
            _log_attempt(db, application, actor_user.email, name, round_day, "interviewer_google_not_connected")
            continue

        slot_times = _slot_times_for_day(round_day)
        batch = _create_batch(
            db, application=application, role="interviewer", interviewer_user_id=interviewer_user.id,
            actor_email=actor_user.email, candidate_name=candidate.full_name, job_title=job.title,
            interviewer_name=name, round_day=round_day, slot_times=slot_times, tracker_path=tracker_path,
        )
        not_available = next(r for r in batch if r.kind == "not_available")
        done = next(r for r in batch if r.kind == "done")
        try:
            send_hr_email(
                hr_integration, to=email, subject=f"Interview scheduling for {job.title}",
                body=_build_interviewer_email_body(
                    candidate.full_name, job.title, round_day, _slot_links(batch), _token_url(not_available.token), _token_url(done.token),
                ),
            )
        except SmtpError:
            # The batch's rows are already committed live (see _create_batch) -- a failed
            # send must not leave them behind for the idempotency guard to trip over.
            # Re-raised unchanged so every existing caller's own SmtpError handling (skip +
            # audit log) still runs exactly as before.
            _invalidate_batch(db, batch)
            raise
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate.full_name or "", "Job Title": job.title, "Assigned Interviewer": name,
                "Slots Offered": ", ".join(_format_slot(t) for t in slot_times),
                "Status": "Awaiting Interviewer Response",
            },
        )
        _log_attempt(db, application, actor_user.email, name, round_day, "offer_sent")
        log_action(
            db, "application", application.id, "interview_negotiation_interviewer_batch_started", actor_user.email,
            {"interviewer": name, "round_day": round_day.isoformat(), "job_title": job.title},
        )
        return "started"

    return "exhausted"


def attempt_auto_negotiate_interview_slots(db: Session, application: Application, actor_user: User) -> Optional[str]:
    """Best-effort automatic trigger for the moment an application's status transitions
    into Shortlisted ('hr_selected') -- same "never block the action that triggered it, just
    skip and log why" contract as app.screening.service.attempt_auto_screen. Callers (the
    shortlisting endpoints) must call this only immediately after they themselves just wrote
    that transition -- never as a periodic sweep over existing 'hr_selected' rows, so an
    application already sitting in that status before this automation existed is never
    retroactively picked up.

    Returns "started" once an interviewer offer went out, or None on any skip (missing
    prerequisite, or the idempotency guard) -- never raises.
    """
    if application.status != "hr_selected":
        return None

    if _has_live_negotiation_or_scheduled_interview(db, application):
        _skip(db, application, actor_user.email, "Application already has a live negotiation, a scheduled interview, or is flagged for manual scheduling")
        return None

    settings_row = get_interview_scheduling_settings(db)
    if not settings_row.tracker_path:
        _skip(db, application, actor_user.email, "Interview Scheduling tracker path is not configured")
        return None
    tracker_path = settings_row.tracker_path

    candidate = db.get(Candidate, application.candidate_id)
    if not candidate or not candidate.email:
        _skip(db, application, actor_user.email, "Candidate has no email on file")
        return None

    job = db.get(JobRole, application.job_role_id)
    if not job:
        _skip(db, application, actor_user.email, "Job not found")
        return None

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        _skip(db, application, actor_user.email, "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails")
        return None

    # Interview Scheduling has no scheduler of its own to keep the Interviewer Pool sheet's
    # Job Title column in sync -- this is the one recurring moment it's actually read from
    # for this flow, same reasoning as the older propose_interview_slots.
    sync_interviewer_pool_job_titles(db, Path(tracker_path))

    now = datetime.now(timezone.utc)
    round_day = _tomorrow_ist(now)

    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, round_day, actor_user, hr_integration)
    except SmtpError as exc:
        _skip(db, application, actor_user.email, str(exc) or "Could not send the interviewer negotiation email")
        return None

    if outcome == "started":
        return "started"

    # Whole pool exhausted for the first day -- one retry, for the day after.
    retry_day = round_day + timedelta(days=1)
    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, retry_day, actor_user, hr_integration)
    except SmtpError as exc:
        _skip(db, application, actor_user.email, str(exc) or "Could not send the interviewer negotiation email")
        return None

    if outcome == "started":
        return "started"

    _flag_for_manual_scheduling(db, application, tracker_path, candidate, job, actor_user.email)
    return None


def advance_after_interviewer_batch_resolved(db: Session, application: Application, batch_round_day: date, actor_email: str) -> None:
    """Called once an interviewer's batch resolves with no slot marked available (a
    "None of these work" click, or "Done" with nothing marked) -- tries the next untried
    interviewer for the SAME round_day. If that day's whole pool is now exhausted: retries
    the day after, but only if `batch_round_day` is the ONLY round_day tried so far for this
    application (never a third day) -- otherwise flags for manual scheduling.
    """
    settings_row = get_interview_scheduling_settings(db)
    if not settings_row.tracker_path:
        return
    tracker_path = settings_row.tracker_path
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if not candidate or not job:
        return
    actor_user = db.query(User).filter(User.email == actor_email).first()
    if actor_user is None:
        return

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        _skip(db, application, actor_email, "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails")
        return

    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, batch_round_day, actor_user, hr_integration)
    except SmtpError:
        return
    if outcome == "started":
        return

    rounds_tried = _distinct_interviewer_round_days(db, application)
    if len(rounds_tried) > 1:
        _flag_for_manual_scheduling(db, application, tracker_path, candidate, job, actor_email)
        return

    retry_day = batch_round_day + timedelta(days=1)
    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, retry_day, actor_user, hr_integration)
    except SmtpError:
        return
    if outcome == "started":
        return
    _flag_for_manual_scheduling(db, application, tracker_path, candidate, job, actor_email)


def start_candidate_round(
    db: Session, application: Application, interviewer_batch: list[NegotiationToken], marked_rows: list[NegotiationToken], actor_email: str,
) -> None:
    """Called once an interviewer's "Done" link is clicked with 1+ slots marked -- emails
    the candidate exactly those slots via the same multi-select token variant, adapted for
    the candidate side (per spec: reuse/adapt the existing candidate-facing email)."""
    settings_row = get_interview_scheduling_settings(db)
    tracker_path = settings_row.tracker_path
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    sample = interviewer_batch[0]
    interviewer_user_id = sample.interviewer_user_id
    interviewer_name = sample.interviewer_name

    if not candidate or not job or not tracker_path:
        return

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        _skip(db, application, actor_email, "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails")
        return

    slot_times = sorted(row.slot_time for row in marked_rows)
    batch = _create_batch(
        db, application=application, role="candidate", interviewer_user_id=interviewer_user_id,
        actor_email=actor_email, candidate_name=candidate.full_name, job_title=job.title,
        interviewer_name=interviewer_name, round_day=sample.round_day, slot_times=slot_times,
        tracker_path=tracker_path,
    )
    not_available = next(r for r in batch if r.kind == "not_available")
    done = next(r for r in batch if r.kind == "done")

    try:
        send_hr_email(
            hr_integration, to=candidate.email, subject=f"Interview scheduling for {job.title}",
            body=_build_candidate_email_body(
                candidate.full_name, job.title, _slot_links(batch), _token_url(not_available.token), _token_url(done.token),
            ),
        )
    except SmtpError as exc:
        # A failed send must not leave this batch's rows live (same reasoning as
        # _advance_interviewer_round), and must not partially proceed as if it had
        # succeeded -- skip means skip, so this returns before the tracker row / audit log
        # below, which describe a round that was actually started.
        _invalidate_batch(db, batch)
        _skip(db, application, actor_email, str(exc) or "Could not send the candidate negotiation email")
        return

    append_interview_log_row(
        Path(tracker_path),
        {
            "Candidate": candidate.full_name or "", "Job Title": job.title, "Assigned Interviewer": interviewer_name or "",
            "Slots Offered": ", ".join(_format_slot(t) for t in slot_times),
            "Status": "Awaiting Candidate Confirmation",
        },
    )
    log_action(
        db, "application", application.id, "interview_negotiation_candidate_round_started", actor_email,
        {"interviewer": interviewer_name, "slots_offered": [t.isoformat() for t in slot_times]},
    )


def finalize_candidate_round(db: Session, application: Application, candidate_marked_rows: list[NegotiationToken], actor_email: str = "candidate") -> None:
    """Called once the candidate's "Done" link is clicked with 1+ slots marked -- picks the
    EARLIEST one, creates the real Calendar event (reusing
    confirmation.create_confirmed_calendar_event unchanged), advances the application to
    'interview_scheduled', and records an Interview row -- same outcome shape the older
    flow's confirm_token already produces, so the Interview List/Dashboard sees it the same
    way regardless of which flow scheduled it."""
    settings_row = get_interview_scheduling_settings(db)
    tracker_path = settings_row.tracker_path

    chosen = min(candidate_marked_rows, key=lambda row: row.slot_time)
    previous_status = application.status
    application.status = "interview_scheduled"

    calendar_event = create_confirmed_calendar_event(db, application, chosen)

    interview = Interview(
        application_id=application.id,
        interviewer_id=chosen.interviewer_user_id,
        scheduled_at=chosen.slot_time,
        calendar_event_id=calendar_event["event_id"] if calendar_event else None,
        calendar_link=calendar_event["html_link"] if calendar_event else None,
        scheduling_method="auto",
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)

    log_action(
        db, "application", application.id, "interview_negotiation_confirmed", actor_email,
        {
            "previous_status": previous_status, "interviewer_name": chosen.interviewer_name,
            "scheduled_at": chosen.slot_time.isoformat(), "calendar_event_created": calendar_event is not None,
            "interview_id": str(interview.id),
        },
    )
    log_action(
        db, "interview", interview.id, "interview_scheduled", actor_email,
        {
            "application_id": str(application.id), "scheduled_at": chosen.slot_time.isoformat(),
            "scheduling_method": "auto", "interviewer_name": chosen.interviewer_name,
        },
    )

    if tracker_path:
        candidate = db.get(Candidate, application.candidate_id)
        job = db.get(JobRole, application.job_role_id)
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate.full_name if candidate else "", "Job Title": job.title if job else "",
                "Assigned Interviewer": chosen.interviewer_name or "",
                "Final Scheduled Time": _format_slot(chosen.slot_time),
                "Candidate Selected Slot": _format_slot(chosen.slot_time),
                "Interviewer Confirmed": "Yes", "Candidate Confirmed": "Yes",
                "Status": "Confirmed",
            },
        )


@dataclass
class NegotiationOutcome:
    status: str  # "recorded" | "declined" | "confirmed" | "invalid" | "expired" | "already_handled"
    message: str
    other_links: list = field(default_factory=list)
    candidate_name: Optional[str] = None
    job_title: Optional[str] = None
    interviewer_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    calendar_link: Optional[str] = None


def _batch_for(db: Session, row: NegotiationToken) -> list[NegotiationToken]:
    """Every row sharing (application_id, role, interviewer_user_id, round_day) with `row`
    -- the same grouping key for both an interviewer batch and the candidate batch it later
    starts (start_candidate_round snapshots the SAME interviewer_user_id and round_day onto
    the candidate-role rows), so one lookup works for either role."""
    return (
        db.query(NegotiationToken)
        .filter(
            NegotiationToken.application_id == row.application_id,
            NegotiationToken.role == row.role,
            NegotiationToken.interviewer_user_id == row.interviewer_user_id,
            NegotiationToken.round_day == row.round_day,
        )
        .all()
    )


def _resolve_declined_batch(db: Session, application: Application, row: NegotiationToken) -> None:
    """Called once a batch resolves with nothing marked available -- for an interviewer
    batch, moves on to the next interviewer (see advance_after_interviewer_batch_resolved);
    for a candidate batch there's no further retry specified, so it goes straight to the
    manual-scheduling flag."""
    if row.role == "interviewer":
        advance_after_interviewer_batch_resolved(db, application, row.round_day, row.actor_email)
        return
    settings_row = get_interview_scheduling_settings(db)
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if settings_row.tracker_path and candidate and job:
        _flag_for_manual_scheduling(db, application, settings_row.tracker_path, candidate, job, row.actor_email)


def handle_negotiation_click(db: Session, token: str) -> NegotiationOutcome:
    """The single entry point behind GET /interview-negotiation/{token} -- every branch
    returns a plain, honest NegotiationOutcome, never raises, same "an expired/used/
    unrecognized link is an expected outcome, not a bug" contract as confirmation.py's own
    confirm_token."""
    now = datetime.now(timezone.utc)
    row = db.query(NegotiationToken).filter(NegotiationToken.token == token).first()

    if row is None:
        return NegotiationOutcome(
            "invalid",
            "This link isn't recognized. Please use the exact link from your email, or contact the "
            "recruiter if you believe this is a mistake.",
        )
    if row.invalidated_at is not None:
        return NegotiationOutcome(
            "already_handled",
            "This negotiation has already been resolved -- if you didn't do this yourself, please "
            "contact the recruiter.",
            candidate_name=row.candidate_name, job_title=row.job_title, interviewer_name=row.interviewer_name,
        )
    if row.expires_at < now:
        return NegotiationOutcome(
            "expired",
            "This link has expired. Please contact the recruiter to arrange a time.",
            candidate_name=row.candidate_name, job_title=row.job_title,
        )

    application = db.get(Application, row.application_id)
    if application is None:
        return NegotiationOutcome(
            "invalid", "This link no longer refers to a valid application. Please contact the recruiter.",
        )

    batch = _batch_for(db, row)

    if row.kind == "slot":
        row.marked_available = True
        row.responded_at = now
        db.commit()
        this_url = _token_url(token)
        not_available = next(r for r in batch if r.kind == "not_available")
        done = next(r for r in batch if r.kind == "done")
        remaining = [link for link in _slot_links(batch) if link["url"] != this_url]
        return NegotiationOutcome(
            "recorded",
            "Got it -- recorded as available. You can click any other time below that also works, then "
            "click \"Done selecting\" once you've marked everything (or \"None of these work\" if you "
            "change your mind).",
            other_links=remaining
            + [
                {"label": "Done selecting -- notify next step now", "url": _token_url(done.token)},
                {"label": "None of these work", "url": _token_url(not_available.token)},
            ],
        )

    for sibling in batch:
        sibling.invalidated_at = now
    row.responded_at = now
    db.commit()

    if row.kind == "not_available":
        _resolve_declined_batch(db, application, row)
        return NegotiationOutcome("declined", "Thanks -- noted.")

    # kind == "done"
    marked = [r for r in batch if r.kind == "slot" and r.marked_available]
    if not marked:
        _resolve_declined_batch(db, application, row)
        return NegotiationOutcome("declined", "Thanks -- noted, no times were marked available.")

    if row.role == "interviewer":
        start_candidate_round(db, application, batch, marked, row.actor_email)
        return NegotiationOutcome(
            "confirmed", "Thanks! We'll now ask the candidate which of those times works for them.",
        )

    # role == "candidate"
    finalize_candidate_round(db, application, marked)
    chosen = min(marked, key=lambda r: r.slot_time)
    return NegotiationOutcome(
        "confirmed", "Your interview is confirmed! We look forward to speaking with you.",
        candidate_name=row.candidate_name, job_title=row.job_title, interviewer_name=row.interviewer_name,
        scheduled_at=chosen.slot_time,
    )
