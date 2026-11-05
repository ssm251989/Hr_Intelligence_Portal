"""Fix 2026-10-04 ("Interview automation"): one way to start interview scheduling after a
shortlist, and never fail silently.

start(): used by a manual shortlist, by the auto-shortlist release (after the undo window) and by
[Send interview times now]. It respects the scheduling mode (company setting
`recruitment.interviews.scheduling_mode`, per-job override `job.shortlisting_json.scheduling_mode`:
"auto" | "manual") and then runs the interviewer-first negotiation (negotiation.py).

When it can't start:
- mailbox problem (send failed) -> retried in the background with backoff (5, 15, 60 min, then
  hourly for 24 h); the profile shows "Interview email not sent - mailbox problem".
- anything else (no interviewer in the job's pool, no free day, no candidate email ...) -> a red
  to-do "Interview not scheduled for <name> - <reason>" on Home, the job and the profile, and the
  recruiter is emailed once per reason.

Background (run_due): releases auto-shortlists whose undo window closed and retries mailbox
failures. It runs in the app's own scheduler when no Celery worker runs (dev / single installs),
and as a Celery beat task otherwise, and writes a heartbeat the Health page checks.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User

log = logging.getLogger(__name__)

PROBLEM_ACTION = "interview_scheduling_problem"
STARTED_ACTION = "interview_scheduling_started"
RETRY_ACTION = "interview_scheduling_retry_scheduled"
MANUAL_MODE_ACTION = "interview_scheduling_manual_mode"
RECRUITER_TOLD_ACTION = "interview_scheduling_recruiter_emailed"
BACKOFF_MINUTES = (5, 15, 60)  # then hourly
GIVE_UP_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def scheduling_mode(db: Session, tenant, job: Optional[JobRole]) -> str:
    from app.platform.settings.resolver import SettingContext, SettingsService

    per_job = ((job.shortlisting_json or {}) if job is not None else {}).get("scheduling_mode")
    if per_job in ("auto", "manual"):
        return per_job
    return SettingsService(db).get("recruitment.interviews.scheduling_mode", SettingContext(tenant=tenant)) or "auto"


def meeting_link_for(db: Session, tenant) -> Optional[str]:
    """The link both people join: the company's fixed room (setting) if set, else a new Jitsi room
    (free, no account) -- no Google Meet / Teams / Zoom connection exists for this flow yet."""
    import secrets

    from app.platform.settings.resolver import SettingContext, SettingsService

    s = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    fixed = (s.get("recruitment.interviews.meeting_link", ctx) or "").strip()
    provider = s.get("recruitment.interviews.meeting_provider", ctx) or "jitsi"
    if fixed:
        return fixed
    if provider == "none":
        return None
    return f"https://meet.jit.si/Interview-{secrets.token_urlsafe(9).replace('_', '').replace('-', '')}"


def _last(db: Session, application_id, actions) -> Optional[AuditLog]:
    return (db.query(AuditLog).filter(AuditLog.entity_id == application_id, AuditLog.action.in_(list(actions)))
            .order_by(AuditLog.created_at.desc()).first())


def _actor_for(db: Session, tenant, job: Optional[JobRole]) -> Optional[User]:
    actor = db.get(User, job.created_by) if job is not None and job.created_by else None
    return actor or db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").order_by(User.created_at).first()


def start(db: Session, tenant, application: Application, actor: Optional[User], *, trigger: str, force: bool = False) -> dict:
    """trigger: manual_shortlist | auto_release | send_now | retry. Never raises; returns
    {"outcome": started|manual_mode|problem|retrying, "reason": ...}."""
    from app.interview_scheduling.negotiation import SEND_FAILED_ACTION, attempt_auto_negotiate_interview_slots

    job = db.get(JobRole, application.job_role_id)
    if not force and scheduling_mode(db, tenant, job) == "manual":
        log_action(db, "application", application.id, MANUAL_MODE_ACTION, "system", {"trigger": trigger})
        db.commit()
        return {"outcome": "manual_mode", "reason": "This job is set to schedule interviews by hand."}
    actor = actor or _actor_for(db, tenant, job)
    if actor is None:
        return _problem(db, tenant, application, job, "There is no user to send the emails as. Add an admin user.", trigger)
    began = _now()
    try:
        outcome, reason = attempt_auto_negotiate_interview_slots(db, application, actor)
    except Exception as exc:  # noqa: BLE001 -- scheduling problems never undo the shortlist
        outcome, reason = None, f"{type(exc).__name__}: {exc}"[:300]
    if outcome == "started":
        log_action(db, "application", application.id, STARTED_ACTION, actor.email[:50], {"trigger": trigger})
        db.commit()
        return {"outcome": "started", "reason": None}
    if reason and "already" in reason.lower() and ("arranging" in reason.lower() or "scheduled" in reason.lower() or "booked" in reason.lower()):
        return {"outcome": "started", "reason": reason}  # a live round / interview exists -- nothing to do
    failed_send = db.query(AuditLog).filter(AuditLog.entity_id == application.id, AuditLog.action == SEND_FAILED_ACTION,
                                            AuditLog.created_at >= began - timedelta(seconds=2)).first() is not None
    if failed_send or (reason and "hr mailbox isn't connected" in reason.lower()):
        return _schedule_retry(db, tenant, application, job, reason or "the mailbox couldn't send", trigger)
    return _problem(db, tenant, application, job, reason or "We couldn't arrange the interview.", trigger)


def _schedule_retry(db: Session, tenant, application: Application, job, reason: str, trigger: str) -> dict:
    prev = _last(db, application.id, (RETRY_ACTION,))
    first_at = datetime.fromisoformat((prev.details or {}).get("first_failed_at")) if prev and trigger == "retry" else _now()
    attempt = int((prev.details or {}).get("attempt", 0)) + 1 if prev and trigger == "retry" else 1
    if _now() - first_at >= timedelta(hours=GIVE_UP_HOURS):
        return _problem(db, tenant, application, job, f"Interview email not sent - mailbox problem ({reason}). We stopped retrying after 24 hours.", trigger)
    wait = BACKOFF_MINUTES[attempt - 1] if attempt <= len(BACKOFF_MINUTES) else 60
    next_at = _now() + timedelta(minutes=wait)
    log_action(db, "application", application.id, RETRY_ACTION, "system",
               {"reason": reason, "attempt": attempt, "next_at": next_at.isoformat(), "first_failed_at": first_at.isoformat(), "trigger": trigger})
    db.commit()
    if attempt == 1:
        _tell_recruiter(db, tenant, application, job, f"Interview email not sent - mailbox problem. We'll keep trying. ({reason})")
    return {"outcome": "retrying", "reason": reason, "next_at": next_at.isoformat()}


def _problem(db: Session, tenant, application: Application, job, reason: str, trigger: str) -> dict:
    log_action(db, "application", application.id, PROBLEM_ACTION, "system", {"reason": reason, "trigger": trigger})
    db.commit()
    _tell_recruiter(db, tenant, application, job, reason)
    return {"outcome": "problem", "reason": reason}


def _tell_recruiter(db: Session, tenant, application: Application, job, reason: str) -> None:
    """Email + in-app note to the job's recruiter, once per reason."""
    from app.integrations.hr_email import SmtpError, get_hr_integration, is_smtp_configured, send_hr_email
    from app.models.comms import OutboundMessage
    from app.recruitment.scoring.autoshortlist import _recipients

    told = db.query(AuditLog).filter(AuditLog.entity_id == application.id, AuditLog.action == RECRUITER_TOLD_ACTION).all()
    if any((t.details or {}).get("reason") == reason for t in told):
        return
    candidate = db.get(Candidate, application.candidate_id)
    name = (candidate.full_name if candidate else None) or "a candidate"
    to = _recipients(db, job, ["job_owner"]) if job is not None else []
    subject = f"Interview not scheduled for {name} - action needed"
    body = (f"The interview for {name} ({job.title if job else 'a job'}) was not scheduled automatically.\n\n"
            f"Reason: {reason}\n\nWhat you can do: add an interviewer with availability (Interviews > Interviewers), "
            f"or book the interview yourself from the candidate's page.\n")
    sent, error = [], None
    hr = get_hr_integration(db)
    if is_smtp_configured(hr):
        for addr in to:
            try:
                send_hr_email(hr, to=addr, subject=subject, body=body)
                sent.append(addr)
            except SmtpError as exc:
                error = str(exc)[:200]
    for addr in to:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.scheduling_problem", to_addresses=[addr],
                               subject=f"Interview not scheduled for {name} - {reason}", body_ref=f"/candidates/{application.id}", status="sent",
                               related_entity_type="application", related_entity_id=application.id))
    log_action(db, "application", application.id, RECRUITER_TOLD_ACTION, "system", {"reason": reason, "emailed": sent, "email_error": error})
    db.commit()


# ---------------------------------------------------------------- what HR sees

def problems(db: Session, tenant, job_id=None) -> list[dict]:
    """Shortlisted candidates whose interview isn't being arranged and needs a person."""
    from app.interview_scheduling.live_status import _live
    from app.models.interview import Interview

    q = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.status == "hr_selected")
    if job_id is not None:
        q = q.filter(Application.job_role_id == job_id)
    out = []
    now = _now()
    for app in q.all():
        last = _last(db, app.id, (PROBLEM_ACTION, STARTED_ACTION, RETRY_ACTION, "interview_negotiation_confirmed"))
        if last is None or last.action not in (PROBLEM_ACTION, RETRY_ACTION):
            continue
        if _live(db, app, now) or db.query(Interview).filter(Interview.application_id == app.id).first() is not None:
            continue
        cand = db.get(Candidate, app.candidate_id)
        job = db.get(JobRole, app.job_role_id)
        details = last.details or {}
        out.append({"application_id": str(app.id), "name": (cand.full_name if cand else None) or "Candidate", "job": job.title if job else None,
                    "kind": "mailbox" if last.action == RETRY_ACTION else "not_scheduled", "reason": details.get("reason"),
                    "next_try_at": details.get("next_at"), "at": last.created_at.isoformat() if last.created_at else None})
    return out


def undo_window(db: Session, application: Application) -> Optional[datetime]:
    """When the auto-shortlist undo window ends, if it is still open and not yet released."""
    from app.recruitment.scoring.autoshortlist import AUTO, RELEASED, UNDONE

    auto = _last(db, application.id, (AUTO,))
    if auto is None or _last(db, application.id, (RELEASED, UNDONE)) is not None:
        return None
    try:
        until = datetime.fromisoformat(str((auto.details or {}).get("undo_until")))
    except ValueError:
        return None
    return until if until > _now() else None


# ---------------------------------------------------------------- background

def run_due(db: Session, tenant) -> dict:
    """Release auto-shortlists past their undo window + retry mailbox failures. Idempotent."""
    from app.recruitment.scoring.autoshortlist import release_due

    released = release_due(db, tenant)
    retried = 0
    now = _now()
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.action == RETRY_ACTION)
            .order_by(AuditLog.created_at.desc()).limit(200).all())
    seen = set()
    for entry in rows:
        if entry.entity_id in seen:
            continue
        seen.add(entry.entity_id)
        latest = _last(db, entry.entity_id, (PROBLEM_ACTION, STARTED_ACTION, RETRY_ACTION, "interview_negotiation_confirmed"))
        if latest is None or latest.id != entry.id:
            continue
        try:
            due = datetime.fromisoformat(str((entry.details or {}).get("next_at")))
        except ValueError:
            continue
        app = db.get(Application, entry.entity_id)
        if due > now or app is None or app.status != "hr_selected":
            continue
        start(db, tenant, app, None, trigger="retry")
        retried += 1
    return {"released": released, "retried": retried}


HEARTBEAT_KEY = "jobs.heartbeat"


def heartbeat(runner: str) -> None:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig

    cp = ControlPlaneSessionLocal()
    try:
        row = cp.get(PlatformConfig, HEARTBEAT_KEY)
        value = {"at": _now().isoformat(), "runner": runner}
        if row is None:
            cp.add(PlatformConfig(key=HEARTBEAT_KEY, value_json=value))
        else:
            row.value_json = value
        cp.commit()
    finally:
        cp.close()


def run_all_tenants(runner: str) -> dict:
    """Every active company, one process at a time (advisory lock)."""
    from sqlalchemy import text

    from app.platform.tenancy.context import tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp = ControlPlaneSessionLocal()
    results = {}
    try:
        if not cp.execute(text("select pg_try_advisory_xact_lock(19041004)")).scalar():
            return {"skipped": "another process is running it"}
        tenants = cp.query(Tenant).filter(Tenant.status == "active").all()
        for t in tenants:
            with tenant_context(t.id, t.slug, t.isolation):
                from app.platform import module_status
                from app.platform.tenancy.context import get_current_tenant

                db = tenant_session(t)
                try:
                    if module_status.is_active(db, get_current_tenant(), "interviews"):
                        results[t.slug] = run_due(db, get_current_tenant())
                except Exception:  # noqa: BLE001
                    log.exception("interview automation failed for %s", t.slug)
                    db.rollback()
                finally:
                    db.close()
        cp.commit()
    finally:
        cp.close()
    heartbeat(runner)
    return results
