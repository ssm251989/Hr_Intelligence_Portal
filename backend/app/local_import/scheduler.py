"""Part G: the every-30-minutes scheduled trigger for run_local_import_scan.

APScheduler's BackgroundScheduler (thread-based) rather than AsyncIOScheduler -- everything
this job touches (the SQLAlchemy session, the synchronous Anthropic client) is sync code, so
a background thread is the natural fit; there's no async event loop involved anywhere in
this job. Wired into app/main.py's lifespan (start on startup, shut down on shutdown) --
this app's first background job, so also its first-ever scheduler.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.local_import.service import run_local_import_scan

logger = logging.getLogger(__name__)

JOB_ID = "local_import_scan"

_scheduler: BackgroundScheduler | None = None


def _run_scheduled_scan() -> None:
    try:
        run_local_import_scan()
    except Exception:
        # A single bad run (e.g. a transient Anthropic outage) must never crash the
        # scheduler thread or stop future scheduled ticks from firing.
        logger.exception("Local import scheduled scan failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_scheduled_scan, trigger=IntervalTrigger(minutes=30), id=JOB_ID)
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
