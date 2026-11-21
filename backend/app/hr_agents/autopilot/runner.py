"""Wakes the automatic agents: events (from the audit log, every minute) and sweeps (schedule).

Events: the audit log is the outbox. Every run reads the application and job events written since the
saved cursor (minus a small safety lag, so a transaction still committing is not skipped) and
calls the agent that owns each event. The cursor is saved per company in autopilot_state.
"""

from app.recruitment.scoring import score_round
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot import briefing, hiring, interviews, jobs, leftovers, people, watchdog
from app.hr_agents.autopilot.core import Run, enabled, record, setting, state_get, state_set

log = logging.getLogger(__name__)

# audit action -> handlers(db, tenant, application, run)
EVENTS: dict[str, tuple[Callable, ...]] = {
    "application_created": (hiring.screen,),
    "ai_screening_scored": (hiring.shortlist_rule,),
    "score_recalculated": (hiring.shortlist_rule,),
    "salary_checked": (hiring.salary,),
    "salary_form_answered": (hiring.salary,),
    "document_uploaded": (hiring.documents,),
    "documents_submitted": (hiring.documents,),
    "bgv_requested": (hiring.bgv_assign,),
    "bgv_vendor_report_received": (hiring.bgv_report,),
    "bgv_passed": (hiring.offer,),
    "bgv_discrepancy": (hiring.offer,),
    "interview_scheduling_manual_mode": (hiring.scheduling,),  # Part 29
}
# Part 29: steps the app's own services take automatically are written to the same agent timeline, so the
# Agents page shows one story per candidate from application to joining (audit action -> agent, outcome, text).
TRACK: dict[str, tuple[str, str, str]] = {
    # the app screens on apply by itself; this puts that step on the timeline (and the event still goes to the shortlist rule)
    "ai_screening_scored": ("screening", "done", "{candidate} was screened: score {score}"),
    "interview_scheduling_started": ("scheduling", "done", "Interview times sent to the interviewer and {candidate}"),
    "interview_confirmed_by_candidate": ("scheduling", "done", "{candidate} confirmed the interview"),
    "interview_scheduling_problem": ("scheduling", "escalated", "Could not arrange {candidate}'s interview - the recruiter was told"),
    "salary_form_sent": ("salary", "done", "Asked {candidate} for salary and joining details"),
    "salary_auto_decided": ("salary", "done", "{candidate}'s salary was inside the company's salary rule and was approved"),
    "documents_approved": ("documents", "done", "{candidate}'s joining documents were approved"),
    "bgv_vendor_assigned": ("bgv", "done", "{candidate}'s BGV was sent to the vendor"),
    "joining_dates_proposed": ("offer", "done", "Joining dates sent to {candidate}"),
    "joining_date_chosen": ("offer", "done", "{candidate} chose a joining date; the offer is being prepared"),
    "offer_sent_for_signing": ("offer", "done", "Offer sent to {candidate} for signing"),
    "offer_signed": ("offer", "done", "{candidate} signed the offer"),
    "welcome_sent": ("onboarding", "done", "Welcome portal sent to {candidate}"),
    "onboarding_completed": ("onboarding", "done", "{candidate} joined"),
}
# Part 30.1: job events (entity_type job_role) -- the Job agent wakes on a new job; the job's own steps go on its timeline.
JOB_EVENTS: dict[str, tuple[Callable, ...]] = {
    "job_role_created": (jobs.job_created,),  # waits for HR to stop editing; prepare_quiet_jobs makes the card
    "job_role_deleted": (),  # nothing to do for the job itself; reading it makes this run close its Publish card
}
JOB_TRACK: dict[str, tuple[str, str, str]] = {
    "job_platforms_published": ("job", "done", "{job} was published ({where})"),
    "job_closed": ("job", "done", "{job} was closed"),
    "job_reopened": ("job", "done", "{job} was reopened"),
    "job_reopened_position_open_again": ("job", "done", "{job} was reopened: a position is open again"),
    "job_auto_closed_deadline_passed": ("job", "done", "{job} closed by itself: the application deadline passed"),
    "job_auto_closed_positions_filled": ("job", "done", "{job} closed by itself: every position is filled"),
}
WHERE = {"career_portal": "careers page", "linkedin": "LinkedIn", "naukri": "Naukri"}
# Part 30.3: interview events (entity_type interview) -- each scorecard may complete the round -> the outcome card
INTERVIEW_EVENTS: dict[str, tuple[Callable, ...]] = {
    "interview_feedback_recorded": (interviews.on_feedback,),
}
CURSOR = "events.cursor"
LAG = timedelta(seconds=20)
BATCH = 500


def run_events(db: Session, tenant, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    upto = now - LAG
    saved = state_get(db, tenant, CURSOR)
    if not setting(db, tenant, "autopilot.enabled"):
        if saved:  # keep the cursor moving: what happens while Autopilot is off is never replayed when it is switched on
            state_set(db, tenant, CURSOR, {"at": upto.isoformat()})
        return {"skipped": "autopilot off"}
    from app.models.application import Application
    from app.models.audit_log import AuditLog

    if not saved:  # first run: start from now, never replay history
        state_set(db, tenant, CURSOR, {"at": upto.isoformat()})
        return {"started": upto.isoformat()}
    from sqlalchemy import and_, or_

    since = datetime.fromisoformat(saved["at"])
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id,
                                      or_(and_(AuditLog.entity_type == "application", AuditLog.action.in_(tuple(EVENTS) + tuple(TRACK))),
                                          and_(AuditLog.entity_type == "job_role", AuditLog.action.in_(tuple(JOB_EVENTS) + tuple(JOB_TRACK))),
                                          and_(AuditLog.entity_type == "interview", AuditLog.action.in_(tuple(INTERVIEW_EVENTS)))),
                                      AuditLog.created_at > since, AuditLog.created_at <= upto)
            .order_by(AuditLog.created_at).limit(BATCH).all())
    handled, seen = 0, set()
    last = since
    for row in rows:
        last = row.created_at
        key = (row.action, row.entity_id)
        if key in seen or row.entity_id is None:
            continue  # one application/job + event once per run
        seen.add(key)
        if row.entity_type == "job_role":
            handled += _job_event(db, tenant, row)
            continue
        if row.entity_type == "interview":
            handled += _interview_event(db, tenant, row)
            continue
        app = db.get(Application, row.entity_id)
        if app is None:
            continue
        if row.action in TRACK:
            handled += _track(db, tenant, app, row)
            if row.action not in EVENTS:
                continue
        for handler in EVENTS[row.action]:
            try:
                if handler(db, tenant, app, Run("event", row.action)) is not None:
                    handled += 1
            except Exception as exc:  # noqa: BLE001 -- one event never blocks the queue
                log.exception("autopilot handler %s failed", handler.__name__)
                db.rollback()
                record(db, tenant, Run("event", row.action), agent=_agent_of(handler), action=handler.__name__, outcome="failed",
                       entity_type="application", entity_id=app.id, summary=f"{handler.__name__} failed: {type(exc).__name__}: {exc}"[:500])
            db.refresh(app)
    state_set(db, tenant, CURSOR, {"at": (last if len(rows) == BATCH else upto).isoformat()})
    out = {"events": len(rows), "handled": handled}
    if enabled(db, tenant, "job", "jobs"):
        out["job_cards"] = jobs.prepare_quiet_jobs(db, tenant, Run("event", "job_role_created"), now=now)
    if rows:  # a step just happened: close the cards it made pointless (the hourly run catches everything else)
        out["cards_closed"] = _close_leftovers(db, tenant, Run("event", "cards"))
    return out


def _close_leftovers(db: Session, tenant, run: Run):
    try:
        return leftovers.close_leftovers(db, tenant, run)
    except Exception as exc:  # noqa: BLE001 -- housekeeping never blocks the agents
        log.exception("autopilot close_leftovers failed")
        db.rollback()
        return f"failed: {type(exc).__name__}"


def _track(db: Session, tenant, application, row) -> int:
    from app.hr_agents.autopilot.core import enabled, names

    agent, outcome, text = TRACK[row.action]
    if not enabled(db, tenant, agent):
        return 0
    if row.action == "salary_auto_decided" and (row.details or {}).get("new_status") != "salary_approved":
        return 0  # the check only routed it to HR (above the band); the Salary agent records its own card
    n = names(db, application)
    job = f" ({n['job']})" if n["job"] else ""
    record(db, tenant, Run("event", row.action), agent=agent, action=f"step_{row.action}"[:60], outcome=outcome, entity_type="application",
           entity_id=application.id, summary=f"{text.format(candidate=n['candidate'], score=score_round(application.composite_score))}{job}.",
           details={"by": row.actor, "audit_id": str(row.id)})
    return 1


def _job_event(db: Session, tenant, row) -> int:
    """A job_role audit row: put the step on the job's timeline (JOB_TRACK) and/or wake the Job agent (JOB_EVENTS)."""
    from app.models.job_role import JobRole

    job = db.get(JobRole, row.entity_id)
    if job is None or job.tenant_id != tenant.tenant_id:
        return 0  # deleted since (the leftover check closes its card)
    handled = 0
    if row.action in JOB_TRACK:
        handled += _track_job(db, tenant, job, row)
    for handler in JOB_EVENTS.get(row.action, ()):
        try:
            if handler(db, tenant, job, Run("event", row.action)) is not None:
                handled += 1
        except Exception as exc:  # noqa: BLE001 -- one event never blocks the queue
            log.exception("autopilot handler %s failed", handler.__name__)
            db.rollback()
            record(db, tenant, Run("event", row.action), agent=_agent_of(handler), action=handler.__name__, outcome="failed",
                   entity_type="job_role", entity_id=job.id, summary=f"{handler.__name__} failed: {type(exc).__name__}: {exc}"[:500])
    return handled


def _interview_event(db: Session, tenant, row) -> int:
    handled = 0
    for handler in INTERVIEW_EVENTS.get(row.action, ()):
        try:
            if handler(db, tenant, row, Run("event", row.action)) is not None:
                handled += 1
        except Exception as exc:  # noqa: BLE001 -- one event never blocks the queue
            log.exception("autopilot handler %s failed", handler.__name__)
            db.rollback()
            record(db, tenant, Run("event", row.action), agent="scheduling", action=handler.__name__, outcome="failed", entity_type="interview",
                   entity_id=row.entity_id, summary=f"{handler.__name__} failed: {type(exc).__name__}: {exc}"[:500])
    return handled


def _track_job(db: Session, tenant, job, row) -> int:
    from app.hr_agents.autopilot.core import enabled

    agent, outcome, text = JOB_TRACK[row.action]
    if not enabled(db, tenant, agent):
        return 0
    details = row.details or {}
    where = ", ".join(label for key, label in WHERE.items() if (details.get("published_platforms") or {}).get(key)) or "no channel chosen"
    record(db, tenant, Run("event", row.action), agent=agent, action=f"step_{row.action}"[:60], outcome=outcome, entity_type="job_role",
           entity_id=job.id, summary=text.format(job=job.title or "The job", where=where) + ".", details={"by": row.actor, "audit_id": str(row.id)})
    return 1


def _agent_of(handler) -> str:
    return {"screen": "screening", "shortlist_rule": "screening", "salary": "salary", "documents": "documents", "bgv_assign": "bgv",
            "bgv_report": "bgv", "offer": "offer", "scheduling": "scheduling", "prepare_publish": "job", "job_created": "job"}.get(handler.__name__, "watchdog")


def run_hourly(db: Session, tenant, trigger: str = "schedule") -> dict:
    """Watchdog + joining day + exits + briefing hour check."""
    if not setting(db, tenant, "autopilot.enabled"):
        return {"skipped": "autopilot off"}
    run = Run(trigger)
    out = {"watchdog": watchdog.run(db, tenant, run)}
    for name, fn in (("joining_day", people.joining_day), ("resignations", people.resignations), ("exit_letters", people.exit_letters),
                     ("briefing", briefing.run)):
        try:
            out[name] = fn(db, tenant, run)
        except Exception as exc:  # noqa: BLE001
            log.exception("autopilot %s failed", name)
            db.rollback()
            out[name] = f"failed: {type(exc).__name__}"
    out["cards_closed"] = _close_leftovers(db, tenant, run)  # last: after this run's own rules (joined, letters)
    return out


def run_daily(db: Session, tenant, trigger: str = "schedule") -> dict:
    if not setting(db, tenant, "autopilot.enabled"):
        return {"skipped": "autopilot off"}
    return {"sourcing": hiring.source_thin_jobs(db, tenant, Run(trigger))}


# what "Run now" on the Autopilot page can start, per agent
RUN_NOW: dict[str, Callable] = {
    "watchdog": lambda db, t: watchdog.run(db, t, Run("manual")),
    "sourcing": lambda db, t: hiring.source_thin_jobs(db, t, Run("manual")),
    "onboarding": lambda db, t: people.joining_day(db, t, Run("manual")),
    "exit": lambda db, t: people.resignations(db, t, Run("manual")) + people.exit_letters(db, t, Run("manual")),
    "briefing": lambda db, t: briefing.run(db, t, Run("manual")),
    "events": lambda db, t: run_events(db, t),
}
