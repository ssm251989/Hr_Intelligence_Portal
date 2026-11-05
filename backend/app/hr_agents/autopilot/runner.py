"""Wakes the automatic agents: events (from the audit log, every minute) and sweeps (schedule).

Events: the audit log is the outbox. Every run reads the application events written since the
saved cursor (minus a small safety lag, so a transaction still committing is not skipped) and
calls the agent that owns each event. The cursor is saved per company in autopilot_state.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot import briefing, hiring, people, watchdog
from app.hr_agents.autopilot.core import Run, record, setting, state_get, state_set

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
}
CURSOR = "events.cursor"
LAG = timedelta(seconds=20)
BATCH = 500


def run_events(db: Session, tenant, now: Optional[datetime] = None) -> dict:
    if not setting(db, tenant, "autopilot.enabled"):
        return {"skipped": "autopilot off"}
    from app.models.application import Application
    from app.models.audit_log import AuditLog

    now = now or datetime.now(timezone.utc)
    upto = now - LAG
    saved = state_get(db, tenant, CURSOR)
    if not saved:  # first run: start from now, never replay history
        state_set(db, tenant, CURSOR, {"at": upto.isoformat()})
        return {"started": upto.isoformat()}
    since = datetime.fromisoformat(saved["at"])
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_type == "application",
                                      AuditLog.action.in_(tuple(EVENTS)), AuditLog.created_at > since, AuditLog.created_at <= upto)
            .order_by(AuditLog.created_at).limit(BATCH).all())
    handled, seen = 0, set()
    last = since
    for row in rows:
        last = row.created_at
        key = (row.action, row.entity_id)
        if key in seen or row.entity_id is None:
            continue  # one application + event once per run
        seen.add(key)
        app = db.get(Application, row.entity_id)
        if app is None:
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
    return {"events": len(rows), "handled": handled}


def _agent_of(handler) -> str:
    return {"screen": "screening", "shortlist_rule": "screening", "salary": "salary", "documents": "documents", "bgv_assign": "bgv",
            "bgv_report": "bgv", "offer": "offer"}.get(handler.__name__, "watchdog")


def run_hourly(db: Session, tenant, trigger: str = "schedule") -> dict:
    """Watchdog + joining day + exits + briefing hour check."""
    if not setting(db, tenant, "autopilot.enabled"):
        return {"skipped": "autopilot off"}
    run = Run(trigger)
    out = {"watchdog": watchdog.run(db, tenant, run)}
    for name, fn in (("joining_day", people.joining_day), ("exit_letters", people.exit_letters), ("briefing", briefing.run)):
        try:
            out[name] = fn(db, tenant, run)
        except Exception as exc:  # noqa: BLE001
            log.exception("autopilot %s failed", name)
            db.rollback()
            out[name] = f"failed: {type(exc).__name__}"
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
    "exit": lambda db, t: people.exit_letters(db, t, Run("manual")),
    "briefing": lambda db, t: briefing.run(db, t, Run("manual")),
    "events": lambda db, t: run_events(db, t),
}
