"""Part G: the scheduled trigger for run_local_import_scan, interval configurable via
local_import_settings.scan_interval_minutes (defaults to 30, the original hardcoded value).

APScheduler's BackgroundScheduler (thread-based) rather than AsyncIOScheduler -- everything
this job touches (the SQLAlchemy session, the synchronous Anthropic client) is sync code, so
a background thread is the natural fit; there's no async event loop involved anywhere in
this job. Wired into app/main.py's lifespan (start on startup, shut down on shutdown) --
this app's first background job, so also its first-ever scheduler.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.local_import.service import run_local_import_scan
from app.local_import.storage import get_local_import_settings

logger = logging.getLogger(__name__)

JOB_ID = "local_import_scan"
DEFAULT_INTERVAL_MINUTES = 30

_scheduler: BackgroundScheduler | None = None


def _run_scheduled_scan() -> None:
    try:
        run_local_import_scan()
    except Exception:
        # A single bad run (e.g. a transient Anthropic outage) must never crash the
        # scheduler thread or stop future scheduled ticks from firing.
        logger.exception("Local import scheduled scan failed")


def _current_interval_minutes() -> int:
    db = SessionLocal()
    try:
        return get_local_import_settings(db).scan_interval_minutes
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler()
    interval_minutes = _current_interval_minutes()
    scheduler.add_job(_run_scheduled_scan, trigger=IntervalTrigger(minutes=interval_minutes), id=JOB_ID)
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reschedule_scan_interval(minutes: int) -> None:
    """Called right after a settings save (see app/local_import/router.py update_settings)
    so a changed interval takes effect on the already-running scheduler immediately --
    no server restart needed. reschedule_job swaps the trigger without resetting the job's
    next-run anchor in a way that loses ticks; APScheduler recomputes next_run_time from
    now using the new interval.

    No-ops if this process has no running scheduler yet (e.g. called outside the app's own
    lifespan, such as directly in a test that never started one) -- the new interval is still
    picked up the next time start_scheduler() runs, since that reads scan_interval_minutes
    fresh from the DB at startup."""
    if _scheduler is None:
        return
    _scheduler.reschedule_job(JOB_ID, trigger=IntervalTrigger(minutes=minutes))
