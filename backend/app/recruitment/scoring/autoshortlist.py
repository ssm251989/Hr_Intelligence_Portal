"""Part 17.6: automated shortlisting (per job, company defaults).

Job's `shortlisting_json` (empty = company defaults, settings `recruitment.shortlisting.*`):
  {"auto_shortlist": bool, "threshold": 0-100 | null, "max_size": int (0 = no limit),
   "undo_hours": business hours, "notify": ["job_owner", "hiring_manager", "<email>"]}

When on: a freshly scored application that is Screened, not knocked out and at/above the
shortlist threshold moves to Shortlisted automatically, the recruiter is told, and an undo
button is shown until the window ends (business hours, company time zone). Interview
scheduling starts only AFTER the window closes (release_due), per the job's scheduling
mode. Never auto-rejects; a person undoing it is final (not auto-shortlisted again).
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.models.user import User

AUTO = "ai_auto_shortlisted"
UNDONE = "auto_shortlist_undone"
RELEASED = "auto_shortlist_released"


def config(db: Session, tenant, job: Optional[JobRole]) -> dict:
    from app.platform.settings.resolver import SettingContext, SettingsService

    s, ctx = SettingsService(db), SettingContext(tenant=tenant)
    cfg = {
        "auto_shortlist": bool(s.get("recruitment.shortlisting.auto_shortlist", ctx)),
        "threshold": None,
        "max_size": int(s.get("recruitment.shortlisting.max_size", ctx) or 0),
        "undo_hours": int(s.get("recruitment.shortlisting.undo_hours", ctx) or 4),
        "notify": list(s.get("recruitment.shortlisting.notify", ctx) or ["job_owner"]),
    }
    own = dict(job.shortlisting_json or {}) if job is not None else {}
    for key in cfg:
        if own.get(key) is not None:
            cfg[key] = own[key]
    return cfg


def _has(db: Session, application_id, action: str) -> bool:
    return db.query(AuditLog.id).filter(AuditLog.entity_type == "application", AuditLog.entity_id == application_id,
                                        AuditLog.action == action).first() is not None


def _recipients(db: Session, job: JobRole, notify: list[str]) -> list[str]:
    out: list[str] = []
    for who in notify:
        if who == "job_owner" and job.created_by:
            u = db.get(User, job.created_by)
            if u and u.email:
                out.append(u.email)
        elif who == "hiring_manager" and job.hiring_manager_id:
            u = db.get(User, job.hiring_manager_id)
            if u and u.email:
                out.append(u.email)
        elif "@" in str(who):
            out.append(str(who).strip().lower())
    if not out:  # nobody named (e.g. a job with no owner) -> the company's admins
        out = [u.email for u in db.query(User).filter(User.tenant_id == job.tenant_id, User.role == "admin").order_by(User.created_at).limit(5) if u.email]
    return sorted(set(out))


def maybe_auto_shortlist(db: Session, tenant, application: Application, *, job: JobRole, threshold: int,
                         knocked_out: bool, actor: str, override: Optional[dict] = None) -> bool:
    """`override` (Part 26, HR Autopilot shortlist rule): config values that win over the company
    defaults, e.g. {"auto_shortlist": True, "threshold": 80}. A job's own setting still wins."""
    from app.experience.ui_screening_router import _add_business_hours, _company_tz
    from app.models.comms import OutboundMessage
    from app.models.candidate import Candidate

    from app.platform import module_status

    if not module_status.is_active(db, tenant, "shortlisting"):
        return False  # Part 19.1: no Shortlisting module -> nothing is shortlisted automatically
    cfg = config(db, tenant, job)
    if override:
        own = dict(job.shortlisting_json or {})
        cfg.update({k: v for k, v in override.items() if own.get(k) is None})
    if not cfg["auto_shortlist"] or application.status != "screened" or knocked_out:
        return False
    if cfg.get("threshold") is not None:
        threshold = int(cfg["threshold"])
    score = float(application.composite_score or 0)
    if score < threshold or _has(db, application.id, UNDONE):
        return False
    if cfg["max_size"]:
        shortlisted = db.query(func.count(Application.id)).filter(
            Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id, Application.status == "hr_selected").scalar() or 0
        if shortlisted >= int(cfg["max_size"]):
            log_action(db, "application", application.id, "auto_shortlist_skipped", "system",
                       {"reason": "shortlist_full", "max_size": cfg["max_size"], "score": score})
            return False
    now = datetime.now(timezone.utc)
    undo_until = _add_business_hours(now, int(cfg["undo_hours"]), _company_tz())
    application.status = "hr_selected"
    application.previous_status = None
    db.commit()
    to = _recipients(db, job, cfg["notify"])
    candidate = db.get(Candidate, application.candidate_id)
    name = (candidate.full_name if candidate else None) or "A candidate"
    for addr in to:
        db.add(OutboundMessage(
            tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.shortlisting", to_addresses=[addr],
            subject=f"{name} was shortlisted automatically for {job.title} (Match score {round(score)}). You can undo this for a few hours.",
            body_ref=f"/candidates/{application.id}", status="sent", related_entity_type="application", related_entity_id=application.id,
        ))
    db.commit()
    log_action(db, "application", application.id, AUTO, actor or "system", {
        "score": score, "threshold": threshold, "undo_until": undo_until.isoformat(), "undo_hours": cfg["undo_hours"],
        "recruiter_notified": bool(to), "notified_to": ", ".join(to) or None, "breakdown": application.score_breakdown,
        "previous_status": "screened", "new_status": "hr_selected",
    })
    from app.shortlisting.service import _salary_after_shortlist

    _salary_after_shortlist(db, application, actor)
    return True


def release_due(db: Session, tenant) -> int:
    """Start interview scheduling for auto-shortlisted candidates whose undo window has
    closed (and who weren't undone). Safe to call often -- each is released once."""
    from app.interview_scheduling import automation

    now = datetime.now(timezone.utc)
    released = 0
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_type == "application", AuditLog.action == AUTO)
            .order_by(AuditLog.created_at.desc()).limit(500).all())
    for entry in rows:
        details = entry.details or {}
        try:
            until = datetime.fromisoformat(str(details.get("undo_until")))
        except ValueError:
            continue
        if until > now or _has(db, entry.entity_id, RELEASED) or _has(db, entry.entity_id, UNDONE):
            continue
        app = db.get(Application, entry.entity_id)
        if app is None or app.status != "hr_selected":
            continue
        job = db.get(JobRole, app.job_role_id)
        actor = db.get(User, job.created_by) if job and job.created_by else None
        if actor is None:
            actor = db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").order_by(User.created_at).first()
        # logged first, so a slow send can't make a second sweep release it again
        log_action(db, "application", app.id, RELEASED, "system", {"trigger": "undo window closed"})
        result = automation.start(db, tenant, app, actor, trigger="auto_release")  # never raises
        log_action(db, "application", app.id, "auto_shortlist_release_result", "system", result)
        released += 1
    return released
