"""Pipeline watchdog (hourly): finds what is stuck anywhere from screening to joining, takes the
next ROUTINE step where there is one, and otherwise tells the person who can unblock it.

Every check is quiet for 24 hours per item after it acted (agent_activity), so people get one
nudge a day, not one an hour. The existing candidate reminders (salary form, documents, joining
dates, BGV vendor) keep running as before; the watchdog acts when those have not helped.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import ACTOR, Run, admins, enabled, job_people, names, notify, record, recently, setting


def run(db: Session, tenant, run_: Run, now: Optional[datetime] = None) -> dict:
    if not enabled(db, tenant, "watchdog"):
        return {"skipped": "off"}
    now = now or datetime.now(timezone.utc)
    hours = int(setting(db, tenant, "autopilot.watchdog.stale_hours") or 48)
    stale = now - timedelta(hours=hours)
    out = {}
    for name, check in CHECKS:
        try:
            out[name] = check(db, tenant, run_, stale, hours, now)
        except Exception as exc:  # noqa: BLE001 -- one check never stops the others
            db.rollback()
            record(db, tenant, run_, agent="watchdog", action=f"check_{name}", outcome="failed", summary=f"Watchdog check '{name}' failed: {type(exc).__name__}: {exc}"[:500])
            out[name] = "failed"
    return out


def _apps(db, tenant, statuses, stale):
    from app.models.application import Application

    return (db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.status.in_(statuses),
                                         Application.removed_at.is_(None), Application.updated_at <= stale).all())


def _escalate(db, tenant, run_, *, action, entity, entity_type, to, subject, link, summary, details=None) -> int:
    if recently(db, tenant, agent="watchdog", action=action, entity_id=entity):
        return 0
    notify(db, tenant, to, subject, link, entity_type=entity_type, entity_id=entity)
    record(db, tenant, run_, agent="watchdog", action=action, outcome="escalated", entity_type=entity_type, entity_id=entity, summary=summary,
           details={"to": sorted(set(to)), **(details or {})})
    return 1


def screened_waiting(db, tenant, run_, stale, hours, now) -> int:
    """Screened candidates nobody has looked at -> one nudge per job to the job owner."""
    from app.models.job_role import JobRole

    by_job: dict = {}
    for app in _apps(db, tenant, ("screened",), stale):
        by_job.setdefault(app.job_role_id, []).append(app)
    n = 0
    for job_id, apps in by_job.items():
        job = db.get(JobRole, job_id)
        if job is None:
            continue
        n += _escalate(db, tenant, run_, action="stale_screened", entity=job.id, entity_type="job_role", to=job_people(db, tenant, job),
                       subject=f"{job.title}: {len(apps)} screened candidate(s) have waited over {hours} h for a shortlist decision.",
                       link="/shortlisting/list", summary=f"{job.title}: {len(apps)} screened candidate(s) waiting over {hours} h - reminded the job owner.",
                       details={"count": len(apps)})
    return n


def salary_waiting(db, tenant, run_, stale, hours, now) -> int:
    from app.recruitment.salary_auto import _approver_emails

    n = 0
    for app in _apps(db, tenant, ("salary_above_band",), stale):
        nm = names(db, app)
        from app.models.job_role import JobRole

        job = db.get(JobRole, app.job_role_id)
        n += _escalate(db, tenant, run_, action="stale_salary", entity=app.id, entity_type="application", to=_approver_emails(db, tenant, job) if job else admins(db, tenant),
                       subject=f"{nm['candidate']} ({nm['job']}) has waited over {hours} h for a salary decision.", link="/salary",
                       summary=f"Salary decision for {nm['candidate']} waiting over {hours} h - reminded the approvers.")
    return n


def documents_waiting(db, tenant, run_, stale, hours, now) -> int:
    """All documents in but not reviewed -> HR; documents still missing after the reminders -> HR may call."""
    from app.recruitment import joining_docs

    n = 0
    for app in _apps(db, tenant, ("salary_approved",), stale):
        st = joining_docs.status(db, tenant, app)
        nm = names(db, app)
        if st["all_received"] and not st["all_approved"]:
            subject = f"{nm['candidate']}'s joining documents are all in and waiting for review."
            summary = f"{nm['candidate']}'s documents waiting for HR review over {hours} h - reminded HR."
        elif st["missing"]:
            subject = f"{nm['candidate']} still hasn't uploaded: {', '.join(st['missing'])} - the reminders didn't help, maybe call."
            summary = f"{nm['candidate']} still missing {', '.join(st['missing'])} after reminders - told HR."
        else:
            continue
        n += _escalate(db, tenant, run_, action="stale_documents", entity=app.id, entity_type="application", to=job_people(db, tenant, _job(db, app)),
                       subject=subject, link=f"/bgv?application={app.id}", summary=summary)
    return n


def bgv_overdue(db, tenant, run_, stale, hours, now) -> int:
    from app.models.agency import BgvAssignment, RecruitmentAgency
    from app.models.application import Application

    n = 0
    today = now.date()
    for a in db.query(BgvAssignment).filter(BgvAssignment.tenant_id == tenant.tenant_id, BgvAssignment.status.in_(("assigned", "in_progress")),
                                            BgvAssignment.due_date.isnot(None), BgvAssignment.due_date < today - timedelta(days=2)).all():
        app = db.get(Application, a.application_id)
        if app is None:
            continue
        nm, ag = names(db, app), db.get(RecruitmentAgency, a.agency_id)
        n += _escalate(db, tenant, run_, action="bgv_overdue", entity=app.id, entity_type="application", to=job_people(db, tenant, _job(db, app)),
                       subject=f"BGV for {nm['candidate']} is {(today - a.due_date).days} days overdue at {ag.name if ag else 'the vendor'} - please call them.",
                       link=f"/bgv?application={app.id}", summary=f"BGV for {nm['candidate']} overdue at {ag.name if ag else 'the vendor'} - told HR.")
    return n


def offers_unsigned(db, tenant, run_, stale, hours, now) -> int:
    """Unsigned offer older than the stale time -> re-sent once by the watchdog; still unsigned a day later -> HR told."""
    from app.models.application import Application
    from app.models.offer import Offer
    from app.offers import revisions

    n = 0
    for offer in db.query(Offer).filter(Offer.tenant_id == tenant.tenant_id, Offer.signed.isnot(True), Offer.sent_at.isnot(None),
                                        Offer.sent_at <= stale).all():
        app = db.get(Application, offer.application_id) if offer.application_id else None
        if app is None or app.status != "offer_sent":
            continue
        nm = names(db, app)
        if not _ever(db, tenant, "resend_offer", app.id):
            try:
                revisions.resend(db, tenant, offer, actor=ACTOR)
            except ValueError:
                db.rollback()
                continue
            record(db, tenant, run_, agent="watchdog", action="resend_offer", outcome="done", entity_type="application", entity_id=app.id,
                   summary=f"{nm['candidate']}'s offer was unsigned for over {hours} h - sent it again.")
            n += 1
            continue
        n += _escalate(db, tenant, run_, action="offer_unsigned", entity=app.id, entity_type="application", to=job_people(db, tenant, _job(db, app)),
                       subject=f"{nm['candidate']} still hasn't signed the offer for {nm['job']}, even after a reminder - maybe call.", link="/offers",
                       summary=f"{nm['candidate']}'s offer still unsigned after the reminder - told the recruiter.")
    return n


def joining_dates_unchosen(db, tenant, run_, stale, hours, now) -> int:
    from app.recruitment import joining_dates

    n = 0
    for app in _apps(db, tenant, ("bgv_cleared",), stale):
        info = joining_dates.info(app)
        if not info.get("proposed") or info.get("chosen"):
            continue
        try:
            at = datetime.fromisoformat(info.get("proposed_at"))
        except (TypeError, ValueError):
            continue
        if at > stale:
            continue
        nm = names(db, app)
        n += _escalate(db, tenant, run_, action="joining_unchosen", entity=app.id, entity_type="application", to=job_people(db, tenant, _job(db, app)),
                       subject=f"{nm['candidate']} hasn't picked a joining date ({', '.join(info['proposed'])}) - maybe call.", link="/offers",
                       summary=f"{nm['candidate']} hasn't chosen a joining date for over {hours} h - told the recruiter.")
    return n


def interview_problems(db, tenant, run_, stale, hours, now) -> int:
    from app.interview_scheduling import automation

    n = 0
    for p in automation.problems(db, tenant):
        from uuid import UUID

        from app.models.application import Application

        app = db.get(Application, UUID(p["application_id"]))
        if app is None:
            continue
        n += _escalate(db, tenant, run_, action="interview_problem", entity=app.id, entity_type="application", to=job_people(db, tenant, _job(db, app)),
                       subject=f"{p['name']}'s interview for {p.get('job') or 'the job'} isn't being arranged ({p.get('reason') or p['kind']}) - needs you.",
                       link="/interviews/list", summary=f"Interview scheduling stuck for {p['name']} ({p.get('reason') or p['kind']}) - told the recruiter.")
    return n


def approvals_waiting(db, tenant, run_, stale, hours, now) -> int:
    """Approval cards (any agent's) pending too long -> one reminder per card to the admins."""
    from app.models.intelligence import AgentSuggestion

    rows = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.status == "pending",
                                             AgentSuggestion.created_at <= stale).order_by(AgentSuggestion.created_at).limit(50).all())
    if not rows or recently(db, tenant, agent="watchdog", action="stale_approvals"):
        return 0
    notify(db, tenant, admins(db, tenant), f"{len(rows)} approval card(s) have waited over {hours} h in My approvals.", "/approvals")
    record(db, tenant, run_, agent="watchdog", action="stale_approvals", outcome="escalated",
           summary=f"{len(rows)} approval card(s) waiting over {hours} h - reminded the admins.", details={"titles": [r.title for r in rows[:10]]})
    return 1


def unscreened(db, tenant, run_, stale, hours, now) -> int:
    """Applications still 'received' an hour after arriving (resume read late, AI was busy) -> screened now."""
    from app.hr_agents.autopilot import hiring

    n = 0
    for app in _apps(db, tenant, ("received",), now - timedelta(hours=1))[:50]:
        if hiring.screen(db, tenant, app, run_) is not None or app.status != "received":
            n += 1
    return n


def _ever(db, tenant, action, entity_id) -> bool:
    from app.models.autopilot import AgentActivity

    return db.query(AgentActivity.id).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.action == action,
                                             AgentActivity.entity_id == entity_id, AgentActivity.outcome == "done").first() is not None


def _job(db, app):
    from app.models.job_role import JobRole

    return db.get(JobRole, app.job_role_id)


CHECKS = (
    ("unscreened", unscreened), ("screened_waiting", screened_waiting), ("interview_problems", interview_problems),
    ("salary_waiting", salary_waiting), ("documents_waiting", documents_waiting), ("bgv_overdue", bgv_overdue),
    ("joining_dates_unchosen", joining_dates_unchosen), ("offers_unsigned", offers_unsigned), ("approvals_waiting", approvals_waiting),
)

