"""Part G: the scheduled trigger for run_local_import_scan, interval configurable via
local_import_settings.scan_interval_minutes (defaults to 30, the original hardcoded value).

Also hosts the shared HR mailbox's IMAP poll (app/integrations/imap_poll.py) -- reuses this
exact same BackgroundScheduler instance as a second registered job, fixed at 30 minutes and
not admin-configurable (unlike the scan above), rather than building a second scheduler.

APScheduler's BackgroundScheduler (thread-based) rather than AsyncIOScheduler -- everything
these jobs touch (the SQLAlchemy session, the synchronous Anthropic client, plain blocking
smtplib/imaplib calls) is sync code, so a background thread is the natural fit; there's no
async event loop involved anywhere here. Wired into app/main.py's lifespan (start on
startup, shut down on shutdown) -- this app's first background job, so also its first-ever
scheduler.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from app.core.config import settings
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.local_import.service import run_local_import_scan
from app.local_import.storage import get_local_import_settings
from app.platform.tenancy.context import TENANT_1_ID, tenant_context

logger = logging.getLogger(__name__)

JOB_ID = "local_import_scan"
DEFAULT_INTERVAL_MINUTES = 30

HR_INBOX_POLL_JOB_ID = "hr_inbox_poll"
HR_INBOX_POLL_INTERVAL_MINUTES = 30

_scheduler: BackgroundScheduler | None = None


def _run_scheduled_scan() -> None:
    # Part 2: see _run_scheduled_hr_inbox_poll's own comment on why this ticks with an
    # explicit tenant_context -- run_local_import_scan's OTHER caller (the manual-trigger
    # endpoint) runs inside a real request and inherits its own TenantContext instead,
    # so that path is deliberately left alone here.
    try:
        with tenant_context(TENANT_1_ID):
            run_local_import_scan()
    except Exception:
        # A single bad run (e.g. a transient Anthropic outage) must never crash the
        # scheduler thread or stop future scheduled ticks from firing.
        logger.exception("Local import scheduled scan failed")


def _run_scheduled_hr_inbox_poll() -> None:
    # Local imports -- avoids a module-level import cycle risk between this module and
    # app.integrations.imap_poll/hr_email, and keeps this scheduler file's own import list
    # focused on what its OTHER job (the scan above) actually needs.
    from app.integrations.hr_email import get_hr_integration
    from app.integrations.imap_poll import ImapError, is_imap_configured, poll_hr_inbox

    # Part 2: this ticks on its own timer, with no request to inherit a TenantContext from
    # -- explicitly the single tenant TENANCY_MODE=single always has (see tenant_context's
    # own docstring; Celery's TenantTask replaces this with real per-tenant fan-out once
    # TENANCY_MODE=multi is actually deployed, Part 13).
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            hr_integration = get_hr_integration(db)
            if not is_imap_configured(hr_integration):
                return
            poll_hr_inbox(db, hr_integration)
        except ImapError:
            # A single bad tick (mailbox unreachable, credentials revoked, ...) must never
            # crash the scheduler thread or stop future ticks from firing -- same treatment
            # as _run_scheduled_scan above.
            logger.exception("HR inbox IMAP poll failed")
        except Exception:
            logger.exception("HR inbox IMAP poll failed")
        finally:
            db.close()


def _current_interval_minutes() -> int:
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            return get_local_import_settings(db).scan_interval_minutes
        finally:
            db.close()


def _run_interview_automation() -> None:
    try:
        from app.interview_scheduling.automation import run_all_tenants

        result = run_all_tenants("in_app")
        if any(isinstance(v, dict) and (v.get("released") or v.get("retried")) for v in result.values()):
            logger.info("interview automation: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("interview automation failed")


def _run_activation_sweep() -> None:
    try:
        from app.platform.activation import sweep

        result = sweep()
        if any(v for k, v in result.items() if k != "skipped"):
            logger.info("activation sweep: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("activation sweep failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler()
    interval_minutes = _current_interval_minutes()
    scheduler.add_job(_run_scheduled_scan, trigger=IntervalTrigger(minutes=interval_minutes), id=JOB_ID)
    scheduler.add_job(
        _run_scheduled_hr_inbox_poll,
        trigger=IntervalTrigger(minutes=HR_INBOX_POLL_INTERVAL_MINUTES),
        id=HR_INBOX_POLL_JOB_ID,
    )
    # Part 19.2b/c: activation emails -- retries with backoff + escalation by priority (one process at a time)
    scheduler.add_job(_run_activation_sweep, trigger=IntervalTrigger(minutes=1), id="activation_sweep")
    # fix 2026-10-04: interview scheduling after the auto-shortlist undo window + mailbox retries.
    # Here (not only in Celery beat) because no Celery worker runs in dev / single installs.
    if settings.INTERVIEW_JOBS_IN_APP:
        scheduler.add_job(_run_interview_automation, trigger=IntervalTrigger(minutes=1), id="interview_automation")
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
