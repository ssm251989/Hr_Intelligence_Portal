"""Part 18.28: the live interview-scheduling status of one application, in plain words, and
the four things HR can do about it from the candidate page.

- status(db, application) -> {state, message, interviewer_name, interviewer_email, sent_at,
  expires_at, round_day, interview_id, can_resend, can_change, can_cancel, can_book}
  state: not_started | waiting_interviewer | waiting_candidate | needs_manual | scheduled |
         done | cancelled
- resend(): the same email again (same link) to whoever we are waiting for.
- change_interviewer(email): stops the current round and offers the times to that person.
- cancel(): stops the automatic arranging (links stop working); HR books it by hand.

Everything is computed from the real rows (negotiation tokens, interviews, audit log), never
from the application's status label.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.negotiation_token import NegotiationToken
from app.models.user import User

CANCELLED_ACTION = "interview_negotiation_cancelled"
RESENT_ACTION = "interview_negotiation_email_resent"
CHANGED_ACTION = "interview_negotiation_interviewer_changed"


class SchedulingActionError(ValueError):
    """Shown to HR as-is (plain words)."""


def _live(db: Session, application: Application, now: datetime) -> list[NegotiationToken]:
    return (db.query(NegotiationToken)
            .filter(NegotiationToken.application_id == application.id, NegotiationToken.invalidated_at.is_(None),
                    NegotiationToken.expires_at > now, NegotiationToken.responded_at.is_(None))
            .order_by(NegotiationToken.created_at.desc()).all())


def _last(db: Session, application: Application, actions: tuple) -> Optional[AuditLog]:
    return (db.query(AuditLog).filter(AuditLog.entity_id == application.id, AuditLog.action.in_(actions))
            .order_by(AuditLog.created_at.desc()).first())


def status(db: Session, application: Application) -> dict:
    from app.interview_scheduling import negotiation as neg

    now = datetime.now(timezone.utc)
    out = {"state": "not_started", "message": None, "interviewer_name": None, "interviewer_email": None, "sent_at": None,
           "expires_at": None, "round_day": None, "interview_id": None, "scheduled_at": None,
           "can_resend": False, "can_change": False, "can_cancel": False, "can_book": False}
    interview = (db.query(Interview).filter(Interview.application_id == application.id)
                 .order_by(Interview.created_at.desc()).first())
    if interview is not None:
        who = interview.interviewer_name or interview.interviewer_email
        if not who and interview.interviewer_id:
            u = db.get(User, interview.interviewer_id)
            who = u.full_name if u else None
        done = interview.decision in ("selected", "rejected")
        out.update(state="done" if done else "scheduled", interview_id=str(interview.id), interviewer_name=who,
                   scheduled_at=interview.scheduled_at.isoformat() if interview.scheduled_at else None)
        return out
    shortlisted = application.status == "hr_selected"
    live = _live(db, application, now)
    if live:
        row = live[0]
        waiting_for = "candidate" if row.role == "candidate" else "interviewer"
        out.update(state=f"waiting_{waiting_for}", interviewer_name=row.interviewer_name, interviewer_email=row.interviewer_email,
                   sent_at=row.created_at.isoformat(), expires_at=row.expires_at.isoformat(), round_day=row.round_day.isoformat(),
                   can_resend=True, can_change=True, can_cancel=True, can_book=True)
        return out
    out["can_book"] = shortlisted
    cancelled = _last(db, application, (CANCELLED_ACTION, neg._RETRY_TRIGGERED_ACTION, neg._BATCH_STARTED_ACTION))
    if cancelled is not None and cancelled.action == CANCELLED_ACTION:
        out.update(state="cancelled", sent_at=cancelled.created_at.isoformat(), can_change=shortlisted)
        return out
    if shortlisted and neg._is_flagged_for_manual_scheduling(db, application):
        out.update(state="needs_manual", can_change=True)
    elif shortlisted:
        out["can_change"] = True
    skip = _last(db, application, ("interview_negotiation_skipped",))
    if skip is not None and out["state"] in ("not_started", "needs_manual"):
        out["message"] = (skip.details or {}).get("reason")
    return out


def _context(db: Session, application: Application):
    from app.integrations.hr_email import get_hr_integration, is_smtp_configured

    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    hr = get_hr_integration(db)
    if not is_smtp_configured(hr):
        raise SchedulingActionError("The HR mailbox isn't connected, so interview emails can't be sent. Connect it in Settings > Communication > Mailboxes.")
    return candidate, job, hr


def resend(db: Session, application: Application, actor: User) -> dict:
    """The same email (same link) again to whoever we are waiting for."""
    from app.integrations.hr_email import SmtpError, send_hr_email
    from app.interview_scheduling import negotiation as neg

    live = _live(db, application, datetime.now(timezone.utc))
    if not live:
        raise SchedulingActionError("There's no interview email waiting for a reply, so there is nothing to resend.")
    row = live[0]
    candidate, job, hr = _context(db, application)
    if row.role == "candidate":
        to = candidate.email if candidate else None
        subject, text_body, html_body = neg._render_negotiation_email(
            db, "recruitment.negotiation.candidate_offer", candidate_name=(candidate.full_name if candidate else None) or "there",
            job_title=job.title, picker_url=neg._token_url(row.token), required_picks=row.required_picks, token_expiry_days=neg.TOKEN_EXPIRY_DAYS)
    else:
        to = row.interviewer_email
        subject, text_body, html_body = neg._render_negotiation_email(
            db, "recruitment.negotiation.interviewer_offer", candidate_name=(candidate.full_name if candidate else None) or "a candidate",
            job_title=job.title, round_day=row.round_day.strftime("%d %b %Y"), picker_url=neg._token_url(row.token),
            required_picks=row.required_picks, token_expiry_days=neg.TOKEN_EXPIRY_DAYS)
    if not to:
        raise SchedulingActionError("We don't have an email address for them.")
    try:
        send_hr_email(hr, to=to, subject=subject, body=text_body, html_body=html_body)
    except SmtpError as exc:
        raise SchedulingActionError(f"We couldn't send the email ({exc}). Check the HR mailbox and try again.") from exc
    log_action(db, "application", application.id, RESENT_ACTION, actor.email, {"to": to, "role": row.role})
    db.commit()
    return status(db, application)


def cancel(db: Session, application: Application, actor: User) -> dict:
    from app.interview_scheduling import negotiation as neg

    live = _live(db, application, datetime.now(timezone.utc))
    if live:
        neg._invalidate_batch(db, live)
    log_action(db, "application", application.id, CANCELLED_ACTION, actor.email, {"stopped_links": len(live)})
    db.commit()
    return status(db, application)


def change_interviewer(db: Session, application: Application, email: str, actor: User) -> dict:
    """Stops the current round (if any) and offers tomorrow's times to this interviewer."""
    from app.experience.ui_interviewers_router import interviewer_problem
    from app.interview_scheduling import negotiation as neg
    from app.integrations.hr_email import SmtpError
    from app.models.interviewer_availability import InterviewerAvailability
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    if application.status != "hr_selected":
        raise SchedulingActionError("This candidate isn't at the Shortlisted step, so there is no interview to arrange.")
    if db.query(Interview).filter(Interview.application_id == application.id).first() is not None:
        raise SchedulingActionError("An interview is already booked for this candidate.")
    email = (email or "").strip().lower()
    problem = interviewer_problem(db, tenant, email)
    if problem:
        raise SchedulingActionError(f"{problem['message']} {problem['fix']}")
    candidate, job, hr = _context(db, application)
    if not candidate or not candidate.email:
        raise SchedulingActionError("The candidate has no email address, so we can't send them interview times. Add their email first.")
    avail = db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id,
                                                     InterviewerAvailability.interviewer_email == email).first()
    name = (avail.interviewer_name if avail else None) or email
    now = datetime.now(timezone.utc)
    live = _live(db, application, now)
    if live:
        neg._invalidate_batch(db, live, now)
    neg.clear_manual_scheduling_flag(db, application, actor.email)
    mechanics = neg._negotiation_mechanics(db, tenant)
    round_day = neg._tomorrow_ist(now)
    slot_times = neg._slot_times_for_day(round_day, mechanics["slot_hours"])
    settings_row = neg.get_interview_scheduling_settings(db)
    try:
        neg._offer_to_interviewer(db, application, candidate, job, settings_row.tracker_path or "app", round_day, actor, hr,
                                  name=name, email=email, mechanics=mechanics, slot_times=slot_times)
    except (SmtpError, neg.NegotiationEmailRenderError, neg.TrackerLockedNegotiationError) as exc:
        raise SchedulingActionError(f"We couldn't send the email to {name} ({exc}). Check the HR mailbox and try again.") from exc
    log_action(db, "application", application.id, CHANGED_ACTION, actor.email, {"interviewer": name, "email": email,
                                                                               "replaced": [r.interviewer_email for r in live]})
    db.commit()
    return status(db, application)


