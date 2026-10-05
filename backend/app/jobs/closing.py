"""Part 18.8: closing and reopening a job by hand.

Close (reason: filled / cancelled / business_hold / other):
- the job goes to "closed" and leaves the careers site (the public pages only show "published");
- every ACTIVE application of the job moves to "On hold - job closed" (status on_hold,
  hold_reason "job_closed", previous_status kept) -- never rejected;
- its queued emails and open interview / scheduling / form links are cancelled;
- the recruiter (job owner + hiring manager) gets an in-app notice;
- if Settings > Hiring > Jobs "email candidates" is on, each candidate gets the editable
  `recruitment.job_closed_candidate` email.
Reopen restores exactly those applications to the stage they were in.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import TERMINAL_APPLICATION_STATUSES, Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.candidates.names import given_name as _given  # fix 2026-10-05: first / preferred name, never the surname

CLOSE_REASONS = ("filled", "cancelled", "business_hold", "other")
JOB_CLOSED = "job_closed"


def _cancel_pending(db: Session, tenant, app_ids: list) -> dict:
    from app.models.comms import OutboundMessage
    from app.models.iam import ActionToken
    from app.models.interview_confirmation_token import InterviewConfirmationToken
    from app.models.negotiation_token import NegotiationToken

    now = datetime.now(timezone.utc)
    done = {"queued_emails": 0, "interview_links": 0, "form_links": 0}
    if not app_ids:
        return done
    for t in db.query(NegotiationToken).filter(NegotiationToken.application_id.in_(app_ids), NegotiationToken.invalidated_at.is_(None)):
        t.invalidated_at = now
        done["interview_links"] += 1
    for t in db.query(InterviewConfirmationToken).filter(InterviewConfirmationToken.application_id.in_(app_ids),
                                                         InterviewConfirmationToken.used_at.is_(None), InterviewConfirmationToken.invalidated_at.is_(None)):
        t.invalidated_at = now
        done["interview_links"] += 1
    for t in db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                          ActionToken.entity_id.in_(app_ids), ActionToken.invalidated_at.is_(None),
                                          ActionToken.responded_at.is_(None), ActionToken.action != "candidate_status_page"):
        t.invalidated_at = now
        done["form_links"] += 1
    for m in db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.status == "queued",
                                              OutboundMessage.related_entity_id.in_(app_ids)):
        m.status, m.error = "suppressed", "job closed"
        done["queued_emails"] += 1
    return done


def _notify_recruiters(db: Session, tenant, job: JobRole, text: str, actor: str) -> list[str]:
    """Job owner, hiring manager and the job's hiring team; if the job has none of them, the
    person who closed it (so the notice always reaches someone)."""
    from app.models.comms import OutboundMessage
    from app.models.hiring_team import JobHiringTeamMember

    ids = [i for i in (job.created_by, job.hiring_manager_id) if i]
    ids += [m.user_id for m in db.query(JobHiringTeamMember).filter(JobHiringTeamMember.tenant_id == tenant.tenant_id,
                                                                     JobHiringTeamMember.job_role_id == job.id) if m.user_id]
    emails = sorted({u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.id.in_(ids or [None])) if u.email})
    if not emails and "@" in actor:
        emails = [actor]
    for addr in emails:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="jobs.closed", to_addresses=[addr], subject=text,
                               body_ref=f"/jobs?job={job.id}", status="sent", related_entity_type="job_role", related_entity_id=job.id))
    return emails


def close_job(db: Session, tenant, job: JobRole, *, reason: str, note: Optional[str], actor: str,
              email_candidates: Optional[bool] = None) -> dict:
    from app.platform.settings.resolver import SettingContext, SettingsService

    if reason not in CLOSE_REASONS:
        raise ValueError(f"reason must be one of {', '.join(CLOSE_REASONS)}")
    if job.status == "closed":
        raise ValueError("This job is already closed.")
    previous = job.status
    now = datetime.now(timezone.utc)
    active = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id,
                                          Application.status.notin_(TERMINAL_APPLICATION_STATUSES + ("on_hold",))).all()
    for app in active:
        app.previous_status, app.status, app.hold_reason = app.status, "on_hold", JOB_CLOSED
    cancelled = _cancel_pending(db, tenant, [a.id for a in active])
    job.status, job.closed_at, job.close_reason, job.close_note = "closed", now, reason, (note or None)
    platforms = dict(job.published_platforms or {})
    platforms["career_portal"] = False
    job.published_platforms = platforms
    notified = _notify_recruiters(db, tenant, job, f"{job.title} was closed ({reason.replace('_', ' ')}). {len(active)} candidate(s) are on hold.", actor)
    db.commit()

    send = email_candidates if email_candidates is not None else bool(
        SettingsService(db).get("recruitment.jobs.close_email_candidates", SettingContext(tenant=tenant)))
    emailed = 0
    if send:
        from app.platform.comms.defaults import send_default

        for app in active:
            cand = db.get(Candidate, app.candidate_id)
            if cand and cand.email:
                try:
                    send_default(db, tenant, "recruitment.job_closed_candidate", to=[cand.email],
                                 ctx={"candidate_name": cand.full_name or "", "candidate_first_name": _given(cand), "job_title": job.title},
                                 related_entity_type="application", related_entity_id=app.id)
                    emailed += 1
                except Exception:  # noqa: BLE001 -- a mail problem never blocks closing the job
                    pass
    result = {"job_id": str(job.id), "previous_status": previous, "on_hold": len(active), "cancelled": cancelled,
              "recruiters_notified": notified, "candidates_emailed": emailed}
    log_action(db, "job_role", job.id, "job_closed", actor[:50], {**result, "reason": reason, "note": note})
    for app in active:
        log_action(db, "application", app.id, "application_put_on_hold", actor[:50], {"previous_status": app.previous_status, "reason": JOB_CLOSED})
    return result


def restore_applications(db: Session, tenant, job: JobRole, *, actor: str) -> int:
    """On reopen: every application the closing put on hold goes back to its stage."""
    restored = 0
    for app in db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id,
                                            Application.status == "on_hold", Application.hold_reason == JOB_CLOSED):
        app.status, app.previous_status, app.hold_reason = app.previous_status or "received", None, None
        restored += 1
        log_action(db, "application", app.id, "application_resumed_from_hold", actor[:50], {"restored_status": app.status, "reason": "job_reopened"})
    job.closed_at = job.close_reason = job.close_note = None
    db.commit()
    return restored
