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
     to exactly one registered User gets emailed ONE link (via the shared HR mailbox, never
     a personal Gmail/Google connection -- hradmin65@gmail.com is the single account of
     record for every interview-scheduling email this mechanic sends) to a page offering 3
     canned times for "tomorrow" (10AM/3PM/6PM) -- pick EXACTLY 2, or decline ("None of
     these work for me").
  4. A decline (or, defensively, anything else the submission handler treats as one) moves
     on to the next interviewer in the pool, for the SAME day.
  5. Once the whole pool is exhausted for a day, retry it once more for the day after --
     tracked by which distinct round_days have actually been tried for this application,
     not by re-deriving "tomorrow" from wall-clock time at whatever moment an interviewer
     happens to respond (which could be days after the negotiation started). If that retry
     also exhausts the pool, the application is flagged for manual scheduling (an Interview
     Log Status row, see _flag_for_manual_scheduling) and nothing further is attempted
     automatically.
  6. Once an interviewer submits their 2 picks, the candidate is independently emailed the
     SAME 3 canned times and asked to also pick exactly 2 -- blind to which 2 the
     interviewer chose.
  7. Once the candidate submits their 2 picks, the overlap between the two pairs is
     computed. With only 3 total slots, 2+2 picks are guaranteed to overlap by the
     pigeonhole principle -- the no-overlap branch below is a defensive path kept for if
     the slot pool ever grows past 3, and re-prompts the CANDIDATE only (the interviewer's
     picks stay fixed). Among the overlapping slot(s), the earliest wins: application.status
     becomes 'interview_scheduled', an Interview row is created, and both the interviewer
     and candidate are emailed a confirmation with a generated .ics invite attached (see
     _finalize) -- this step never touches the Google Calendar API (unlike the older
     confirmation.create_confirmed_calendar_event, still used unchanged by the manual
     "Propose Slots" flow), since that needs a live, per-interviewer OAuth refresh token
     that has already been seen to fail in real use, silently leaving both parties without
     any invite despite the interview being marked scheduled.

Idempotency: attempt_auto_negotiate_interview_slots below is the only entry point, called
right after the Shortlisted transition itself (never a periodic sweep, see its own
docstring) -- it refuses to start a second negotiation for an application that already has
a live token, a scheduled Interview, or an already-logged manual-scheduling flag.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.config import settings
from app.integrations.google_calendar import APP_TIMEZONE, DEFAULT_INTERVIEW_DURATION_MINUTES, format_ist_datetime
from app.integrations.hr_email import EmailAttachment, get_hr_integration, is_smtp_configured, send_hr_email, SmtpError
from app.integrations.ics import build_interview_ics
from app.interview_scheduling.service import _find_interviewer_user
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

# How many of SLOT_HOURS_IST a recipient must pick -- exactly, not "at least". Named so the
# validation in submit_negotiation_response and the frontend JS enable/disable logic in
# render_negotiation_page both read from the same source of truth.
REQUIRED_PICKS = 2

# Same window InterviewConfirmationToken already uses for its own links -- no reason for a
# different lifetime for this flow's own links.
TOKEN_EXPIRY_DAYS = 5

_SKIP_ACTION = "interview_negotiation_skipped"
_ATTEMPT_ACTION = "interview_negotiation_interviewer_attempt"
_MANUAL_ACTION = "interview_negotiation_manual_scheduling_required"
_BATCH_STARTED_ACTION = "interview_negotiation_interviewer_batch_started"
_INTERVIEWER_RESPONDED_ACTION = "interview_negotiation_interviewer_responded"
_CANDIDATE_ROUND_STARTED_ACTION = "interview_negotiation_candidate_round_started"
_CANDIDATE_RESPONDED_ACTION = "interview_negotiation_candidate_responded"
_CANDIDATE_REPROMPTED_ACTION = "interview_negotiation_candidate_reprompted"
_CONFIRMED_ACTION = "interview_negotiation_confirmed"
_RETRY_TRIGGERED_ACTION = "interview_negotiation_retry_triggered"
_STALE_TOKENS_INVALIDATED_ACTION = "interview_negotiation_stale_tokens_invalidated"
# _MANUAL_ACTION is an audit-log-based flag with no dedicated "clear" column -- logging this
# newer, superseding entry IS the clear mechanism (see _is_flagged_for_manual_scheduling,
# which reads the MOST RECENT of {_MANUAL_ACTION, this}, not "was _MANUAL_ACTION ever
# logged"). Logged by retry_negotiation on every retry, right before re-running the guard
# that reads it -- the exact incident this exists to fix: once flagged, the old "ever
# logged" check blocked every future retry forever, even one specifically meant to un-stick
# it, since check_retry_eligibility never checked this condition and kept reporting
# ELIGIBLE. Deliberately excluded from NEGOTIATION_STATUS_ACTIONS below, same reasoning as
# _RETRY_TRIGGERED_ACTION -- always immediately followed by a real outcome action.
_MANUAL_SCHEDULING_CLEARED_ACTION = "interview_negotiation_manual_scheduling_cleared"

# Every "what happened to this application's negotiation" action, latest-one-wins -- the
# single signal app.candidates.router row_to_item exposes as negotiation_status (so a
# "Retry Scheduling" action can tell "the last attempt was skipped" apart from "still
# pending" or "already resolved" without a separate, independently-maintained flag).
# _RETRY_TRIGGERED_ACTION/_STALE_TOKENS_INVALIDATED_ACTION/_INTERVIEWER_RESPONDED_ACTION/
# _CANDIDATE_RESPONDED_ACTION/_MANUAL_SCHEDULING_CLEARED_ACTION are deliberately excluded --
# each is always immediately followed by a real outcome action from this same set (or a
# fresh skip), so including them would never change which one is "latest".
NEGOTIATION_STATUS_ACTIONS = (
    _SKIP_ACTION,
    _MANUAL_ACTION,
    _BATCH_STARTED_ACTION,
    _CANDIDATE_ROUND_STARTED_ACTION,
    _CONFIRMED_ACTION,
)

# How long a still-live (not invalidated, not expired) negotiation token is treated as
# genuinely mid-flight -- just sent, its recipient simply hasn't responded yet -- rather
# than orphaned (the exact pre-_invalidate_batch incident this retry path exists to clean
# up automatically, see check_retry_eligibility/retry_negotiation below).
# 10 minutes is generous next to how fast a real send+skip round-trips (milliseconds), so it
# only ever protects against a genuine race (e.g. a double-click on Retry) -- never a real
# multi-day wait for an interviewer's email response, since retry_negotiation is only ever
# reached after check_retry_eligibility, which the frontend only offers once the LAST
# negotiation status for this application is already a skip (see NEGOTIATION_STATUS_ACTIONS
# above) -- a genuinely still-pending token never reaches this check in normal use.
RETRY_MIDFLIGHT_WINDOW = timedelta(minutes=10)


def _skip(db: Session, application: Application, actor_email: str, reason: str) -> None:
    log_action(db, "application", application.id, _SKIP_ACTION, actor_email, {"reason": reason})


def _tomorrow_ist(now: datetime) -> date:
    return (now.astimezone(APP_TIMEZONE) + timedelta(days=1)).date()


def _slot_times_for_day(day: date) -> list[datetime]:
    return [datetime.combine(day, hour, tzinfo=APP_TIMEZONE).astimezone(timezone.utc) for hour in SLOT_HOURS_IST]


def _format_slot(slot_time: datetime) -> str:
    return format_ist_datetime(slot_time)


def _in_flight_or_scheduled_reason(
    db: Session, application: Application, now: datetime, *, live_token_max_age: Optional[timedelta] = None,
) -> Optional[str]:
    """The single shared source of truth for "why can't a negotiation start or retry right
    now" -- covers the two conditions that must always mean the same thing wherever they're
    checked: an Interview row already exists, or a live token is still within
    `live_token_max_age` of its own creation (None means ANY age blocks). Shared by
    _has_live_negotiation_or_scheduled_interview (max_age=None -- a fresh Shortlisted-
    transition trigger must never fire alongside a live token of any age) and
    check_retry_eligibility (max_age=RETRY_MIDFLIGHT_WINDOW -- an OLDER live token is
    tolerated there, since retry_negotiation is about to invalidate it as orphaned rather
    than genuinely pending) -- previously these were two independently hand-rolled checks,
    which is exactly how they drifted on the manual-scheduling-required condition (see
    _is_flagged_for_manual_scheduling's own docstring). That condition is deliberately NOT
    included here -- see _has_live_negotiation_or_scheduled_interview for why.
    """
    live_token = (
        db.query(NegotiationToken)
        .filter(
            NegotiationToken.application_id == application.id,
            NegotiationToken.invalidated_at.is_(None),
            NegotiationToken.expires_at > now,
        )
        .order_by(NegotiationToken.created_at.desc())
        .first()
    )
    if live_token is not None and (live_token_max_age is None or now - live_token.created_at < live_token_max_age):
        if live_token_max_age is not None:
            minutes = int(live_token_max_age.total_seconds() // 60)
            return f"A negotiation was started less than {minutes} minutes ago and may still be in flight -- wait before retrying"
        return "Application already has a live negotiation in progress"
    if db.query(Interview).filter(Interview.application_id == application.id).first() is not None:
        return "An interview has already been scheduled for this application"
    return None


def _is_flagged_for_manual_scheduling(db: Session, application: Application) -> bool:
    """True iff the MOST RECENT of {_MANUAL_ACTION, _MANUAL_SCHEDULING_CLEARED_ACTION} for
    this application is a flag -- not "a flag was ever logged" (the exact bug this replaces:
    once flagged, every future retry was silently skipped forever, even one specifically
    meant to un-stick it, since check_retry_eligibility never checked this condition at all
    and kept reporting ELIGIBLE). See retry_negotiation, which logs
    _MANUAL_SCHEDULING_CLEARED_ACTION on every retry attempt, right before re-running this
    same check."""
    latest = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action.in_((_MANUAL_ACTION, _MANUAL_SCHEDULING_CLEARED_ACTION)))
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    return latest is not None and latest.action == _MANUAL_ACTION


def clear_manual_scheduling_flag(db: Session, application: Application, actor_email: str) -> None:
    """Logs the one audit entry that supersedes any earlier interview_negotiation_manual_
    scheduling_required flag for this application -- see _is_flagged_for_manual_scheduling,
    which reads the MOST RECENT of {flag, this}, never "was it ever flagged."

    Call this before ANY attempt_auto_negotiate_interview_slots call that's meant to start
    a genuinely new negotiation cycle -- both retry_negotiation's own manual retry below
    AND a fresh Shortlisted transition (see app/shortlisting/router.py's three call sites).
    Before this was added to the shortlisting flow too, a flag left over from an earlier,
    unrelated shortlisting cycle for the same application silently blocked the next
    genuinely fresh one -- no interviewer ever contacted, no error surfaced anywhere,
    since attempt_auto_negotiate_interview_slots' own "never block the action that
    triggered it" contract means a skip here is deliberately silent by design (the exact
    incident this fixes, see Kranthi Kumar's real one).

    Idempotent to call even when nothing is currently flagged -- always logged
    unconditionally, cheaper than reading first and harmless when there was nothing to
    clear (same reasoning retry_negotiation's own stale-token cleanup already uses).
    """
    log_action(db, "application", application.id, _MANUAL_SCHEDULING_CLEARED_ACTION, actor_email, {})


_MANUAL_STAGE_RESET_TO_SCREENING_ACTION = "manual_stage_reset_to_screening"


def reset_application_to_screening(db: Session, application: Application, actor_email: str, reason: str) -> None:
    """The manual support action for moving an application back from Shortlisted
    ('hr_selected') to Screening ('screened') -- e.g. a shortlist decision made in error, or
    (as originally done for Kranthi Kumar/Kishore Reddy/Arjun Reddy) to give a fresh
    shortlisting decision a clean slate. Also clears any manual-scheduling-required flag
    left over from the cycle being reversed -- the exact thing the first two ad hoc uses of
    this action (run as one-off scripts, before this function existed) didn't do, which is
    part of why a flag from that earlier cycle went on to silently block the next real,
    fresh Shortlisted transition (see clear_manual_scheduling_flag's own docstring)."""
    previous_status = application.status
    application.status = "screened"
    db.add(application)
    clear_manual_scheduling_flag(db, application, actor_email)
    log_action(
        db, "application", application.id, _MANUAL_STAGE_RESET_TO_SCREENING_ACTION, actor_email,
        {"previous_status": previous_status, "new_status": "screened", "reason": reason},
    )
    db.commit()


def _has_live_negotiation_or_scheduled_interview(db: Session, application: Application, now: Optional[datetime] = None) -> Optional[str]:
    """Returns the reason attempt_auto_negotiate_interview_slots must not start a second,
    overlapping negotiation for this application, or None if clear: a live (not yet
    invalidated/expired) negotiation token of any age, an existing Interview row (scheduled
    through this flow, the older flow, or the fully-manual endpoint), or a still-flagged
    manual-scheduling-required marker (see _is_flagged_for_manual_scheduling).

    The first two conditions are shared with check_retry_eligibility via
    _in_flight_or_scheduled_reason so they can never independently drift again. The manual-
    scheduling condition is deliberately NOT shared -- check_retry_eligibility must keep
    reporting ELIGIBLE for an application stuck on exactly that flag, since un-sticking it is
    this whole retry mechanism's reason to exist (see its own docstring: "Manual escape hatch
    for an application stuck at Shortlisted"). retry_negotiation clears the flag before this
    guard ever runs again, which is what actually resolves the contradiction rather than
    hiding it behind a shared check."""
    now = now or datetime.now(timezone.utc)
    reason = _in_flight_or_scheduled_reason(db, application, now, live_token_max_age=None)
    if reason is not None:
        return reason
    if _is_flagged_for_manual_scheduling(db, application):
        return "Application is flagged for manual scheduling and needs a human to pick it up"
    return None


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


def _build_interviewer_email_body(candidate_name: Optional[str], job_title: str, round_day: date, picker_url: str) -> str:
    return (
        f"Hi,\n\n"
        f"We'd like you to interview {candidate_name or 'a candidate'} for the {job_title} role, "
        f"on {round_day.strftime('%d %b %Y')}. Please pick exactly {REQUIRED_PICKS} of the 3 time "
        f"options that work for you:\n\n{picker_url}\n\n"
        f"This link expires in {TOKEN_EXPIRY_DAYS} days.\n\nThanks!"
    )


def _build_candidate_email_body(candidate_name: Optional[str], job_title: str, picker_url: str) -> str:
    return (
        f"Hi {candidate_name or 'there'},\n\n"
        f"We'd like to schedule your interview for the {job_title} position. Please pick exactly "
        f"{REQUIRED_PICKS} of the 3 time options that work best for you:\n\n{picker_url}\n\n"
        f"This link expires in {TOKEN_EXPIRY_DAYS} days. Thanks!"
    )


# --- HTML counterparts of the two plain-text builders above -- same audience-specific
# copy, sent as the multipart/alternative HTML part (see hr_email.send_hr_email's
# html_body param) so the email itself matches the branded look the negotiation page
# already has (negotiation_router.py's own navy-to-blue CTD Techs shell/button styling),
# rather than landing on a fully-branded page from a plain-text email. Deliberately plain
# table/inline-style HTML, not the page's own <style> block -- most email clients (Outlook
# desktop above all) never render a <head><style> block or CSS gradients, so every visual
# choice here has to survive as inline styles with a solid bgcolor fallback. ---

_EMAIL_FONT_FAMILY = "-apple-system, Segoe UI, Roboto, Arial, sans-serif"


def _negotiation_email_html(heading_html: str, body_copy_html: str, picker_url: str) -> str:
    """The shared shell both _build_interviewer_email_html/_build_candidate_email_html fill
    in -- header band, heading + body copy, CTA button, footer -- so the two audiences can
    never visually drift apart. `heading_html`/`body_copy_html` are assumed already
    HTML-escaped by the caller (candidate/job-title/date interpolation happens there, right
    next to the plain-text version that needs the exact same escaping discipline)."""
    picker_url_attr = escape(picker_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interview Scheduling</title>
</head>
<body style="margin:0; padding:0; background-color:#eef1f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eef1f6;">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background-color:#ffffff; border-radius:12px;">
<tr>
<td bgcolor="#1d5fd6" style="background-color:#1d5fd6; background-image:linear-gradient(120deg, #0b1f4d, #1d5fd6); border-radius:12px 12px 0 0; padding:22px 32px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td bgcolor="#5b7cff" style="width:30px; height:30px; border-radius:8px; background-color:#5b7cff; background-image:linear-gradient(135deg, #4f9dff, #7b5cff); font-size:0; line-height:0;">&nbsp;</td>
<td style="padding-left:10px; font-family:{_EMAIL_FONT_FAMILY}; font-size:15px; font-weight:700; letter-spacing:0.04em; color:#f5f8ff;">CTD TECHS</td>
</tr></table>
</td>
</tr>
<tr>
<td style="padding:32px;">
<h1 style="margin:0 0 12px; font-family:{_EMAIL_FONT_FAMILY}; font-size:22px; font-weight:800; color:#0b1f4d;">{heading_html}</h1>
<p style="margin:0 0 26px; font-family:{_EMAIL_FONT_FAMILY}; font-size:15px; line-height:1.6; color:#3a4257;">{body_copy_html}</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td bgcolor="#1d5fd6" style="border-radius:10px; background-color:#1d5fd6;">
<a href="{picker_url_attr}" target="_blank" style="display:inline-block; padding:13px 26px; font-family:{_EMAIL_FONT_FAMILY}; font-size:14px; font-weight:700; color:#ffffff; text-decoration:none; border-radius:10px;">Choose Your Available Slots</a>
</td>
</tr></table>
<p style="margin:22px 0 0; font-family:{_EMAIL_FONT_FAMILY}; font-size:12px; line-height:1.5; color:#8a93a6;">Or copy and paste this link into your browser:<br>
<a href="{picker_url_attr}" style="color:#1d5fd6; word-break:break-all;">{picker_url_attr}</a></p>
</td>
</tr>
<tr>
<td style="padding:16px 32px; background-color:#f6f8fc; border-top:1px solid #e6eaf3; border-radius:0 0 12px 12px; font-family:{_EMAIL_FONT_FAMILY}; font-size:13px; color:#5b6478;">
This link expires in {TOKEN_EXPIRY_DAYS} days.<br>
Need help? Reply to this email or contact your recruiter.
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _build_interviewer_email_html(candidate_name: Optional[str], job_title: str, round_day: date, picker_url: str) -> str:
    name_html = escape(candidate_name or "a candidate")
    job_html = escape(job_title)
    date_html = escape(round_day.strftime("%d %b %Y"))
    body_copy_html = (
        f"We'd like you to interview <strong style=\"color:#1d5fd6;\">{name_html}</strong> for the "
        f"{job_html} role, on {date_html}. Please pick exactly {REQUIRED_PICKS} of the 3 time options "
        f"that work for you."
    )
    return _negotiation_email_html("Hi,", body_copy_html, picker_url)


def _build_candidate_email_html(candidate_name: Optional[str], job_title: str, picker_url: str) -> str:
    name_html = escape(candidate_name or "there")
    job_html = escape(job_title)
    body_copy_html = (
        f"We'd like to schedule your interview for the <strong style=\"color:#1d5fd6;\">{job_html}</strong> "
        f"position. Please pick exactly {REQUIRED_PICKS} of the 3 time options that work best for you."
    )
    return _negotiation_email_html(f"Hi {name_html},", body_copy_html, picker_url)


def _token_url(token: str) -> str:
    return f"{settings.APP_BASE_URL}/interview-negotiation/{token}"


def _create_negotiation_row(
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
    tracker_path: str,
    now: Optional[datetime] = None,
) -> NegotiationToken:
    now = now or datetime.now(timezone.utc)
    row = NegotiationToken(
        application_id=application.id, role=role, interviewer_user_id=interviewer_user_id,
        actor_email=actor_email, candidate_name=candidate_name, job_title=job_title,
        interviewer_name=interviewer_name, round_day=round_day,
        tracker_path=str(tracker_path), token=secrets.token_urlsafe(32),
        # Explicit Python wall-clock time, not the column's server_default=now() -- Postgres
        # now() is pinned to the enclosing transaction's start time, so two rows created
        # moments apart in the SAME transaction (e.g. a defensive candidate re-prompt, which
        # invalidates the old row and creates a new one in one call) would otherwise get an
        # IDENTICAL created_at, breaking _find_current_row's "most recently created" lookup.
        created_at=now,
        expires_at=now + timedelta(days=TOKEN_EXPIRY_DAYS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _invalidate_batch(db: Session, rows: list[NegotiationToken], now: Optional[datetime] = None) -> None:
    """_create_negotiation_row above already commits a row before the caller ever attempts
    to send its email -- if that send then fails, the row must not survive as live, or
    _has_live_negotiation_or_scheduled_interview's idempotency guard blocks every retry of
    this application for up to TOKEN_EXPIRY_DAYS even after the send issue itself is fixed
    (the exact orphaned-token incident this exists to prevent). Takes a list (not a single
    row) since check_retry_eligibility/retry_negotiation's stale-cleanup can find more than
    one still-live row at once."""
    now = now or datetime.now(timezone.utc)
    for row in rows:
        row.invalidated_at = now
    db.commit()


def _find_current_row(
    db: Session, application_id, role: str, interviewer_user_id, round_day: date
) -> Optional[NegotiationToken]:
    """The most-recently-created row for this (application, role, interviewer, round_day)
    key -- there's normally exactly one (this table's own docstring: only one LIVE row per
    key at a time), but a defensive candidate re-prompt (see _reprompt_candidate) can leave
    an earlier, now-invalidated row behind too, so "most recent" rather than "the only one"
    is the safe lookup."""
    return (
        db.query(NegotiationToken)
        .filter(
            NegotiationToken.application_id == application_id,
            NegotiationToken.role == role,
            NegotiationToken.interviewer_user_id == interviewer_user_id,
            NegotiationToken.round_day == round_day,
        )
        .order_by(NegotiationToken.created_at.desc())
        .first()
    )


def _flag_for_manual_scheduling(db: Session, application: Application, tracker_path: str, candidate: Candidate, job: JobRole, actor_email: str) -> None:
    append_interview_log_row(
        Path(tracker_path),
        {"Candidate": candidate.full_name or "", "Job Title": job.title, "Status": "Manual Scheduling Required"},
    )
    log_action(
        db, "application", application.id, _MANUAL_ACTION, actor_email,
        {"job_title": job.title, "candidate_name": candidate.full_name},
    )


def _flag_send_failed(db: Session, application: Application, tracker_path: str, candidate: Candidate, job: JobRole) -> None:
    """The Interview Log's only visible record that this application's negotiation email
    failed to send -- distinct from _flag_for_manual_scheduling's "Manual Scheduling
    Required" (a clean pool exhaustion, nobody available) so a recruiter scanning the
    tracker can tell "nobody free, needs a human to schedule" apart from "this needs
    POST .../retry-negotiation once the mailbox/interviewer issue itself is fixed" at a
    glance. Before this, a send failure was visible only in audit_log's
    interview_negotiation_skipped entry (see _skip), invisible from the tracker a
    recruiter actually works out of day to day."""
    append_interview_log_row(
        Path(tracker_path),
        {"Candidate": candidate.full_name or "", "Job Title": job.title, "Status": "Send Failed - Retry Needed"},
    )


def _advance_interviewer_round(
    db: Session, application: Application, candidate: Candidate, job: JobRole, tracker_path: str,
    round_day: date, actor_user: User, hr_integration,
) -> str:
    """Walks the job's Interviewer Pool, in order, for `round_day`, skipping anyone already
    attempted for this exact (application, round_day) pair (see _already_attempted_names --
    derived from audit_log, not a separate counter, so this is safely re-callable any number
    of times as interviewers respond asynchronously), busy this week, missing a Mails-sheet
    email, or not resolving to exactly one registered User. Starts a negotiation row for and
    emails the first interviewer who clears every check, returning "started"; returns
    "exhausted" once the whole pool has been walked with nobody clearing them all.

    Deliberately does NOT require the interviewer to have their own personal Google
    connection (unlike the older service.py select_interviewer flow, which still needs one
    per interviewer to run its own real-time Calendar availability check) -- the shared HR
    mailbox (hradmin65@gmail.com) is this app's single account of record for every email
    this mechanic sends, interviewer and candidate alike, and availability here is decided
    entirely by tracker.interviewer_busy_this_week's own Excel-log heuristic, which reads
    nothing from any personal calendar. An interviewer needs only a registered User
    account to be reachable -- never a Google connection of their own.
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

        row = _create_negotiation_row(
            db, application=application, role="interviewer", interviewer_user_id=interviewer_user.id,
            actor_email=actor_user.email, candidate_name=candidate.full_name, job_title=job.title,
            interviewer_name=name, round_day=round_day, tracker_path=tracker_path,
        )
        try:
            send_hr_email(
                hr_integration, to=email, subject=f"Interview scheduling for {job.title}",
                body=_build_interviewer_email_body(candidate.full_name, job.title, round_day, _token_url(row.token)),
                html_body=_build_interviewer_email_html(candidate.full_name, job.title, round_day, _token_url(row.token)),
            )
        except SmtpError:
            # The row is already committed live (see _create_negotiation_row) -- a failed
            # send must not leave it behind for the idempotency guard to trip over.
            # Re-raised unchanged so every existing caller's own SmtpError handling (skip +
            # audit log) still runs exactly as before.
            _invalidate_batch(db, [row])
            raise
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate.full_name or "", "Job Title": job.title, "Assigned Interviewer": name,
                "Slots Offered": ", ".join(_format_slot(t) for t in _slot_times_for_day(round_day)),
                "Status": "Awaiting Interviewer Response",
            },
        )
        _log_attempt(db, application, actor_user.email, name, round_day, "offer_sent")
        log_action(
            db, "application", application.id, _BATCH_STARTED_ACTION, actor_user.email,
            {"interviewer": name, "round_day": round_day.isoformat(), "job_title": job.title},
        )
        return "started"

    return "exhausted"


def attempt_auto_negotiate_interview_slots(db: Session, application: Application, actor_user: User) -> tuple[Optional[str], Optional[str]]:
    """Best-effort automatic trigger for the moment an application's status transitions
    into Shortlisted ('hr_selected'), or a manual retry of the exact same logic (see
    check_retry_eligibility/retry_negotiation below) -- same "never block the action that
    triggered it, just skip and log why" contract as app.screening.service.attempt_auto_screen.
    Callers (the shortlisting endpoints) must call this only immediately after they
    themselves just wrote that transition -- never as a periodic sweep over existing
    'hr_selected' rows, so an application already sitting in that status before this
    automation existed is never retroactively picked up.

    Returns (outcome, reason): outcome is "started" once an interviewer offer went out, or
    None on any skip (missing prerequisite, or the idempotency guard); reason is the actual
    human-readable cause whenever outcome is None (surfaced by retry_negotiation through
    RetryNegotiationResponse.reason so the frontend never has to fall back to generic
    "check the tracker" copy), None when outcome is "started". Never raises.
    """
    if application.status != "hr_selected":
        return None, "Application is not in Shortlisted status"

    blocking_reason = _has_live_negotiation_or_scheduled_interview(db, application)
    if blocking_reason:
        _skip(db, application, actor_user.email, blocking_reason)
        return None, blocking_reason

    settings_row = get_interview_scheduling_settings(db)
    if not settings_row.tracker_path:
        reason = "Interview Scheduling tracker path is not configured"
        _skip(db, application, actor_user.email, reason)
        return None, reason
    tracker_path = settings_row.tracker_path

    candidate = db.get(Candidate, application.candidate_id)
    if not candidate or not candidate.email:
        reason = "Candidate has no email on file"
        _skip(db, application, actor_user.email, reason)
        return None, reason

    job = db.get(JobRole, application.job_role_id)
    if not job:
        reason = "Job not found"
        _skip(db, application, actor_user.email, reason)
        return None, reason

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        reason = "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails"
        _skip(db, application, actor_user.email, reason)
        return None, reason

    # Interview Scheduling has no scheduler of its own to keep the Interviewer Pool sheet's
    # Job Title column in sync -- this is the one recurring moment it's actually read from
    # for this flow, same reasoning as the older propose_interview_slots.
    sync_interviewer_pool_job_titles(db, Path(tracker_path))

    now = datetime.now(timezone.utc)
    round_day = _tomorrow_ist(now)

    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, round_day, actor_user, hr_integration)
    except SmtpError as exc:
        reason = str(exc) or "Could not send the interviewer negotiation email"
        _skip(db, application, actor_user.email, reason)
        _flag_send_failed(db, application, tracker_path, candidate, job)
        return None, reason

    if outcome == "started":
        return "started", None

    # Whole pool exhausted for the first day -- one retry, for the day after.
    retry_day = round_day + timedelta(days=1)
    try:
        outcome = _advance_interviewer_round(db, application, candidate, job, tracker_path, retry_day, actor_user, hr_integration)
    except SmtpError as exc:
        reason = str(exc) or "Could not send the interviewer negotiation email"
        _skip(db, application, actor_user.email, reason)
        _flag_send_failed(db, application, tracker_path, candidate, job)
        return None, reason

    if outcome == "started":
        return "started", None

    _flag_for_manual_scheduling(db, application, tracker_path, candidate, job, actor_user.email)
    return None, f"No eligible interviewer was available for {job.title} on the day(s) tried -- this application needs to be scheduled manually"


def _live_tokens(db: Session, application: Application, now: Optional[datetime] = None) -> list[NegotiationToken]:
    now = now or datetime.now(timezone.utc)
    return (
        db.query(NegotiationToken)
        .filter(
            NegotiationToken.application_id == application.id,
            NegotiationToken.invalidated_at.is_(None),
            NegotiationToken.expires_at > now,
        )
        .all()
    )


def check_retry_eligibility(db: Session, application: Application, now: Optional[datetime] = None) -> Optional[str]:
    """Returns None if `application` is eligible for POST .../retry-negotiation, or a
    human-readable reason it isn't. Deliberately independent of
    app.shortlisting.service.update_shortlist_status's own terminal-SHORTLISTED rule --
    retrying isn't a status change (the human shortlist decision this followed is
    unchanged), it's re-running the scheduling logistics that should already have followed
    it, so that rule must never be the thing standing in the way of a retry.

    Three conditions, all required:
      - status is still 'hr_selected' (Shortlisted) -- once an interview is actually
        scheduled through this flow, _finalize already moves status to
        'interview_scheduled', so this is also what keeps retry from ever re-firing a
        negotiation that in fact succeeded.
      - no Interview row exists yet for this application, and no live token is still within
        RETRY_MIDFLIGHT_WINDOW of its own creation -- shared with attempt_auto_negotiate_
        interview_slots' own idempotency guard via _in_flight_or_scheduled_reason (see its
        docstring for why these two conditions must never be checked independently again),
        parameterized only by that window -- the one condition that's a judgment call
        rather than a hard invariant (see RETRY_MIDFLIGHT_WINDOW's own comment).

    Deliberately does NOT check whether the application is flagged for manual scheduling
    (_is_flagged_for_manual_scheduling) -- unlike the two conditions above, that one must
    NOT be shared with the guard: this whole endpoint exists specifically as the escape
    hatch for an application stuck on exactly that flag, so it must keep reporting ELIGIBLE
    for one. retry_negotiation clears the flag itself before ever reaching the guard again,
    which is what actually makes "ELIGIBLE" correct rather than just optimistic.
    """
    now = now or datetime.now(timezone.utc)
    if application.status != "hr_selected":
        return "Application is not in Shortlisted status"
    return _in_flight_or_scheduled_reason(db, application, now, live_token_max_age=RETRY_MIDFLIGHT_WINDOW)


def retry_negotiation(db: Session, application: Application, actor_user: User) -> tuple[Optional[str], int, Optional[str]]:
    """POST .../retry-negotiation's implementation. Caller (the router) must call
    check_retry_eligibility first and reject an ineligible application with an HTTP error
    before ever reaching this.

    Defensively invalidates any live token left over for this application -- the exact
    manual NegotiationToken cleanup this stuck-application incident used to require by
    hand, now automatic -- before re-invoking attempt_auto_negotiate_interview_slots
    exactly as if this were the original Shortlisted transition. Only a token OLDER than
    RETRY_MIDFLIGHT_WINDOW can still be live here (check_retry_eligibility already rejected
    anything more recent), so anything this invalidates is, by that same judgment call,
    orphaned rather than genuinely pending.

    Also clears any manual-scheduling-required flag left over from a previous attempt (see
    _MANUAL_SCHEDULING_CLEARED_ACTION's own comment) -- right before re-invoking the guard
    that reads it, so a retry can actually un-stick an application that got flagged that
    way, rather than silently re-tripping the same guard forever.

    Returns (outcome, invalidated_count, reason) -- outcome/reason are attempt_auto_
    negotiate_interview_slots' own return value, invalidated_count is how many stale token
    rows were cleaned up first (0 most of the time, now that _invalidate_batch runs inline
    on every send failure -- non-zero only for a token that predates that fix, or some other
    reason it was left live without resolving).
    """
    now = datetime.now(timezone.utc)
    stale = _live_tokens(db, application, now)
    if stale:
        _invalidate_batch(db, stale, now)
        log_action(
            db, "application", application.id, _STALE_TOKENS_INVALIDATED_ACTION, actor_user.email,
            {"invalidated_count": len(stale)},
        )
    log_action(db, "application", application.id, _RETRY_TRIGGERED_ACTION, actor_user.email, {})
    clear_manual_scheduling_flag(db, application, actor_user.email)
    outcome, reason = attempt_auto_negotiate_interview_slots(db, application, actor_user)
    return outcome, len(stale), reason


def advance_after_interviewer_batch_resolved(db: Session, application: Application, batch_round_day: date, actor_email: str) -> None:
    """Called once an interviewer declines (or, defensively, otherwise resolves without
    submitting valid picks) -- tries the next untried interviewer for the SAME round_day.
    If that day's whole pool is now exhausted: retries the day after, but only if
    `batch_round_day` is the ONLY round_day tried so far for this application (never a
    third day) -- otherwise flags for manual scheduling.
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


def _start_candidate_round(db: Session, application: Application, interviewer_row: NegotiationToken) -> None:
    """Called once an interviewer submits their 2 picks -- emails the candidate the SAME 3
    canned times independently (see _build_candidate_email_body), blind to which 2 the
    interviewer chose."""
    settings_row = get_interview_scheduling_settings(db)
    tracker_path = settings_row.tracker_path
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if not candidate or not job or not tracker_path:
        return

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        _skip(db, application, interviewer_row.actor_email, "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails")
        return

    row = _create_negotiation_row(
        db, application=application, role="candidate", interviewer_user_id=interviewer_row.interviewer_user_id,
        actor_email=interviewer_row.actor_email, candidate_name=candidate.full_name, job_title=job.title,
        interviewer_name=interviewer_row.interviewer_name, round_day=interviewer_row.round_day, tracker_path=tracker_path,
    )
    try:
        send_hr_email(
            hr_integration, to=candidate.email, subject=f"Interview scheduling for {job.title}",
            body=_build_candidate_email_body(candidate.full_name, job.title, _token_url(row.token)),
            html_body=_build_candidate_email_html(candidate.full_name, job.title, _token_url(row.token)),
        )
    except SmtpError as exc:
        # Same reasoning as _advance_interviewer_round's own SmtpError handling -- a failed
        # send must not leave this row live, and must not partially proceed as if it had
        # succeeded (no tracker row / audit log below, which describe a round that was
        # actually started).
        _invalidate_batch(db, [row])
        _skip(db, application, interviewer_row.actor_email, str(exc) or "Could not send the candidate negotiation email")
        return

    append_interview_log_row(
        Path(tracker_path),
        {
            "Candidate": candidate.full_name or "", "Job Title": job.title,
            "Assigned Interviewer": interviewer_row.interviewer_name or "",
            "Status": "Awaiting Candidate Response",
        },
    )
    log_action(
        db, "application", application.id, _CANDIDATE_ROUND_STARTED_ACTION, interviewer_row.actor_email,
        {"interviewer": interviewer_row.interviewer_name},
    )


def _resolve_declined(db: Session, application: Application, row: NegotiationToken) -> None:
    """Called once a token resolves declined -- for an interviewer row, moves on to the
    next interviewer (see advance_after_interviewer_batch_resolved); for a candidate row
    there's no further retry specified, so it goes straight to the manual-scheduling flag."""
    if row.role == "interviewer":
        advance_after_interviewer_batch_resolved(db, application, row.round_day, row.actor_email)
        return
    settings_row = get_interview_scheduling_settings(db)
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if settings_row.tracker_path and candidate and job:
        _flag_for_manual_scheduling(db, application, settings_row.tracker_path, candidate, job, row.actor_email)


def _reprompt_candidate(db: Session, application: Application, candidate_row: NegotiationToken) -> "NegotiationPageState":
    """Defensive path -- with only 3 total canned slots, an interviewer's 2 picks and a
    candidate's 2 picks are guaranteed to overlap by the pigeonhole principle (any 2 of 3
    must include at least one of the interviewer's own 2), so this can never actually fire
    in real usage today. Kept, and tested directly (by forcing a no-overlap result rather
    than trying to construct real data that produces one), for if the slot pool ever grows
    past 3, where a genuine no-overlap becomes possible.

    Re-prompts the CANDIDATE only -- the interviewer's picks stay fixed, interviewer_row is
    never touched -- and only once: a second no-overlap in a row falls back to manual
    scheduling rather than looping forever."""
    already_reprompted = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == _CANDIDATE_REPROMPTED_ACTION)
        .first()
        is not None
    )
    settings_row = get_interview_scheduling_settings(db)
    tracker_path = settings_row.tracker_path
    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)

    if already_reprompted or not tracker_path or not candidate or not job:
        if tracker_path and candidate and job:
            _flag_for_manual_scheduling(db, application, tracker_path, candidate, job, candidate_row.actor_email)
        return NegotiationPageState(status="declined", row=candidate_row)

    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        _skip(db, application, candidate_row.actor_email, "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails")
        return NegotiationPageState(status="declined", row=candidate_row)

    new_row = _create_negotiation_row(
        db, application=application, role="candidate", interviewer_user_id=candidate_row.interviewer_user_id,
        actor_email=candidate_row.actor_email, candidate_name=candidate_row.candidate_name, job_title=candidate_row.job_title,
        interviewer_name=candidate_row.interviewer_name, round_day=candidate_row.round_day, tracker_path=tracker_path,
    )
    try:
        send_hr_email(
            hr_integration, to=candidate.email, subject=f"Interview scheduling for {job.title}",
            body=_build_candidate_email_body(candidate.full_name, job.title, _token_url(new_row.token)),
            html_body=_build_candidate_email_html(candidate.full_name, job.title, _token_url(new_row.token)),
        )
    except SmtpError as exc:
        _invalidate_batch(db, [new_row])
        _skip(db, application, candidate_row.actor_email, str(exc) or "Could not send the candidate negotiation email")
        return NegotiationPageState(status="declined", row=candidate_row)

    log_action(
        db, "application", application.id, _CANDIDATE_REPROMPTED_ACTION, candidate_row.actor_email,
        {"round_day": candidate_row.round_day.isoformat()},
    )
    return NegotiationPageState(status="candidate_reprompted", row=candidate_row)


def _build_confirmation_email_body(candidate_name: Optional[str], job_title: str, interviewer_name: Optional[str], chosen_time: datetime, duration_minutes: int) -> str:
    return (
        f"Hi,\n\n"
        f"This confirms the interview for {candidate_name or 'the candidate'} for the {job_title} "
        f"role with {interviewer_name or 'the interviewer'}.\n\n"
        f"Date/Time: {_format_slot(chosen_time)}\n"
        f"Duration: {duration_minutes} minutes\n"
        f"Mode: Video call (link in the attached calendar invite)\n\n"
        f"A calendar invite is attached -- open it to add this to your calendar.\n\nThanks!"
    )


def _send_confirmation_email(hr_integration, *, to: str, job_title: str, body: str, ics_bytes: bytes) -> bool:
    """Best-effort per recipient, same philosophy the old Google Calendar path already
    had (a missing/broken connection is logged, never blocks a confirmation that's already
    been recorded) -- except here the only way this can fail is the shared HR mailbox's own
    SMTP connection, not a per-interviewer OAuth token, so a failure here means the mailbox
    itself needs attention rather than one interviewer's stale Google connection."""
    try:
        send_hr_email(
            hr_integration, to=to, subject=f"Interview confirmed: {job_title}", body=body,
            attachment=EmailAttachment(filename="interview.ics", content=ics_bytes, maintype="text", subtype="calendar"),
        )
        return True
    except SmtpError:
        return False


def _finalize(db: Session, application: Application, candidate_row: NegotiationToken, chosen_time: datetime) -> "NegotiationPageState":
    """Advances the application to 'interview_scheduled' and records an Interview row --
    same outcome shape the older flow's confirm_token already produces, so the Interview
    List/Dashboard sees it the same way regardless of which flow scheduled it.

    Confirms BOTH parties by emailing each an .ics calendar invite through the shared HR
    mailbox's SMTP connection (app/integrations/ics.py + hr_email.send_hr_email) rather
    than creating a Google Calendar event -- this mechanic's final step no longer touches
    the Google Calendar API at all (see module docstring above for why: a real negotiation
    has already been seen to reach this point with an expired/revoked per-interviewer OAuth
    token, silently leaving both parties without any invite despite the interview being
    marked scheduled). The older manual/propose-slots flow is untouched and still uses
    confirmation.create_confirmed_calendar_event."""
    settings_row = get_interview_scheduling_settings(db)
    tracker_path = settings_row.tracker_path

    previous_status = application.status
    application.status = "interview_scheduled"

    interview = Interview(
        application_id=application.id,
        interviewer_id=candidate_row.interviewer_user_id,
        scheduled_at=chosen_time,
        scheduling_method="auto",
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)

    candidate = db.get(Candidate, application.candidate_id)
    interviewer = db.get(User, candidate_row.interviewer_user_id) if candidate_row.interviewer_user_id else None
    duration_minutes = candidate_row.duration_minutes or DEFAULT_INTERVIEW_DURATION_MINUTES
    job_title = candidate_row.job_title or ""
    candidate_name = candidate.full_name if candidate else candidate_row.candidate_name

    interviewer_sent = False
    candidate_sent = False
    hr_integration = get_hr_integration(db)
    if is_smtp_configured(hr_integration) and candidate is not None and candidate.email and interviewer is not None and interviewer.email:
        ics_bytes = build_interview_ics(
            start=chosen_time, duration_minutes=duration_minutes,
            summary=f"Interview: {candidate_name or 'Candidate'} — {job_title}",
            organizer_email=hr_integration.from_address or hr_integration.smtp_username,
            attendee_emails=[interviewer.email, candidate.email],
            description=f"Interview confirmed for application {application.id}.",
        )
        body = _build_confirmation_email_body(candidate_name, job_title, candidate_row.interviewer_name, chosen_time, duration_minutes)
        interviewer_sent = _send_confirmation_email(hr_integration, to=interviewer.email, job_title=job_title, body=body, ics_bytes=ics_bytes)
        candidate_sent = _send_confirmation_email(hr_integration, to=candidate.email, job_title=job_title, body=body, ics_bytes=ics_bytes)

    log_action(
        db, "application", application.id, _CONFIRMED_ACTION, "candidate",
        {
            "previous_status": previous_status, "interviewer_name": candidate_row.interviewer_name,
            "scheduled_at": chosen_time.isoformat(), "interview_id": str(interview.id),
            "interviewer_confirmation_sent": interviewer_sent, "candidate_confirmation_sent": candidate_sent,
        },
    )
    log_action(
        db, "interview", interview.id, "interview_scheduled", "candidate",
        {
            "application_id": str(application.id), "scheduled_at": chosen_time.isoformat(),
            "scheduling_method": "auto", "interviewer_name": candidate_row.interviewer_name,
        },
    )

    if tracker_path:
        job = db.get(JobRole, application.job_role_id)
        append_interview_log_row(
            Path(tracker_path),
            {
                "Candidate": candidate.full_name if candidate else "", "Job Title": job.title if job else "",
                "Assigned Interviewer": candidate_row.interviewer_name or "",
                "Final Scheduled Time": _format_slot(chosen_time),
                "Candidate Selected Slot": _format_slot(chosen_time),
                "Interviewer Confirmed": "Yes", "Candidate Confirmed": "Yes",
                "Status": "Confirmed",
            },
        )

    return NegotiationPageState(status="confirmed", row=candidate_row, scheduled_at=chosen_time)


def _resolve_candidate_submission(db: Session, application: Application, candidate_row: NegotiationToken) -> "NegotiationPageState":
    """Computes the overlap between candidate_row's own 2 picks and the corresponding
    interviewer row's 2 picks (independently submitted, blind to each other). The earliest
    overlapping slot wins; an empty overlap (unreachable at 3 total slots -- see
    _reprompt_candidate) re-prompts the candidate instead."""
    interviewer_row = _find_current_row(
        db, application.id, "interviewer", candidate_row.interviewer_user_id, candidate_row.round_day
    )
    interviewer_picks = set((interviewer_row.selected_slots or [])) if interviewer_row else set()
    candidate_picks = set(candidate_row.selected_slots or [])
    overlap = sorted(candidate_picks & interviewer_picks)
    if not overlap:
        return _reprompt_candidate(db, application, candidate_row)
    return _finalize(db, application, candidate_row, datetime.fromisoformat(overlap[0]))


@dataclass
class NegotiationPageState:
    """Everything render_negotiation_page (app/interview_scheduling/negotiation_router.py)
    needs to render either the interactive pick-2-of-3 form or one of the terminal outcome
    states, for GET (always "form" or a terminal status) and POST (a terminal status, or
    "form" again with `error` set when the submission wasn't exactly 2 picks) alike.

    status:
      "form"                 -- show the picker; `error` is set on a re-render after an
                                 invalid submission (row is never None here).
      "invalid"               -- token not recognized.
      "expired"               -- token recognized but past expires_at.
      "already_handled"       -- token recognized but already responded/invalidated.
      "declined"              -- this recipient declined ("None of these work for me").
      "interviewer_submitted" -- interviewer's 2 picks recorded; candidate contacted next.
      "candidate_reprompted"  -- defensive no-overlap path; candidate asked again.
      "confirmed"             -- the interview is actually scheduled (scheduled_at set).
    """

    status: str
    row: Optional[NegotiationToken] = None
    error: Optional[str] = None
    checked_isos: list = field(default_factory=list)
    scheduled_at: Optional[datetime] = None


def _lookup_row(db: Session, token: str, now: datetime) -> tuple[str, Optional[NegotiationToken]]:
    row = db.query(NegotiationToken).filter(NegotiationToken.token == token).first()
    if row is None:
        return "invalid", None
    if row.invalidated_at is not None:
        return "already_handled", row
    if row.expires_at < now:
        return "expired", row
    return "pending", row


def get_negotiation_form(db: Session, token: str, now: Optional[datetime] = None) -> NegotiationPageState:
    """The single entry point behind GET /interview-negotiation/{token}."""
    now = now or datetime.now(timezone.utc)
    status, row = _lookup_row(db, token, now)
    if status != "pending":
        return NegotiationPageState(status=status, row=row)
    return NegotiationPageState(status="form", row=row)


def submit_negotiation_response(
    db: Session, token: str, *, action: str, selected_isos: list[str], now: Optional[datetime] = None
) -> NegotiationPageState:
    """The single entry point behind POST /interview-negotiation/{token}. `action` is
    "decline" or "submit" (the form's two distinct submit buttons); `selected_isos` is
    whatever the "slots" checkboxes sent, deduped and filtered down to this round_day's real
    3 canned times before anything is trusted -- a submission is only ever accepted with
    exactly REQUIRED_PICKS of those. An invalid count re-renders the same form with `error`
    set rather than failing outright, since a JS-disabled browser or a slow double-submit
    can genuinely reach this without any bad intent."""
    now = now or datetime.now(timezone.utc)
    status, row = _lookup_row(db, token, now)
    if status != "pending":
        return NegotiationPageState(status=status, row=row)

    application = db.get(Application, row.application_id)
    if application is None:
        return NegotiationPageState(status="invalid", row=None)

    if action == "decline":
        row.responded_at = now
        row.invalidated_at = now
        db.commit()
        _resolve_declined(db, application, row)
        return NegotiationPageState(status="declined", row=row)

    valid_isos = {t.isoformat() for t in _slot_times_for_day(row.round_day)}
    chosen = [iso for iso in dict.fromkeys(selected_isos) if iso in valid_isos]
    if len(chosen) != REQUIRED_PICKS:
        return NegotiationPageState(
            status="form", row=row, checked_isos=chosen,
            error=f"Please select exactly {REQUIRED_PICKS} time options before submitting.",
        )

    row.responded_at = now
    row.invalidated_at = now
    row.selected_slots = chosen
    db.commit()

    if row.role == "interviewer":
        log_action(
            db, "application", application.id, _INTERVIEWER_RESPONDED_ACTION, row.actor_email,
            {"interviewer": row.interviewer_name, "round_day": row.round_day.isoformat(), "selected_slots": chosen},
        )
        _start_candidate_round(db, application, row)
        return NegotiationPageState(status="interviewer_submitted", row=row)

    log_action(
        db, "application", application.id, _CANDIDATE_RESPONDED_ACTION, row.actor_email,
        {"round_day": row.round_day.isoformat(), "selected_slots": chosen},
    )
    return _resolve_candidate_submission(db, application, row)
