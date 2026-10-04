"""Background work inside the backend (owner request 2026-10-04: one reliable local option).

Without Redis there is no Celery worker, so nothing on the Celery beat schedule ran (reminders,
the 24 h salary-form reminder, document / joining reminders, approval timers, report schedules,
onboarding chase, Recycle-bin clean-up ...). When JOBS_IN_APP is on (default when REDIS_URL is
not set) the backend runs every one of those itself, on the same intervals as the beat schedule,
for every active company:

- one process at a time per job (Postgres advisory lock), so two backends never double-send;
- a job that belongs to a module the company doesn't have is skipped (module_registry.JOB_MODULE);
- each run records {last_run, ok, error, result} in platform_config["jobs.status"], which the
  Health page shows (green / red, last run time).

The interview automation (every minute) and the activation sweep (every minute) are registered
separately (local_import/scheduler.py) and report into the same status.
"""

import logging
import zlib
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
STATUS_KEY = "jobs.status"


def record(name: str, interval_seconds: float, ok: bool, result=None, error: str | None = None) -> None:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig

    cp = ControlPlaneSessionLocal()
    try:
        row = cp.get(PlatformConfig, STATUS_KEY)
        value = dict(row.value_json) if row is not None and isinstance(row.value_json, dict) else {}
        value[name] = {"last_run": datetime.now(timezone.utc).isoformat(), "ok": ok, "every_seconds": interval_seconds,
                       "result": str(result)[:200] if result is not None else None, "error": (error or "")[:300] or None}
        if row is None:
            cp.add(PlatformConfig(key=STATUS_KEY, value_json=value))
        else:
            row.value_json = value
        cp.commit()
    except Exception:  # noqa: BLE001 -- status bookkeeping never breaks a job
        log.exception("could not record job status for %s", name)
        cp.rollback()
    finally:
        cp.close()


def status() -> dict:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig

    cp = ControlPlaneSessionLocal()
    try:
        row = cp.get(PlatformConfig, STATUS_KEY)
        return dict(row.value_json) if row is not None and isinstance(row.value_json, dict) else {}
    finally:
        cp.close()


def run_job(name: str, interval_seconds: float) -> None:
    """One scheduled job for every active company (same work the Celery fan_out does)."""
    from sqlalchemy import text

    from app.platform.jobs.scheduled import JOBS, _module_guard
    from app.platform.tenancy.context import get_current_tenant, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp = ControlPlaneSessionLocal()
    results, errors = {}, []
    try:
        if not cp.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": zlib.crc32(f"job:{name}".encode())}).scalar():
            return  # another process is running it right now
        for t in cp.query(Tenant).filter(Tenant.status == "active").all():
            with tenant_context(t.id, t.slug, t.isolation):
                db = tenant_session(t)
                try:
                    results[t.slug] = _module_guard(name, JOBS[name])(db, get_current_tenant())
                except Exception as exc:  # noqa: BLE001 -- one company's failure never stops the others
                    log.exception("job %s failed for %s", name, t.slug)
                    db.rollback()
                    errors.append(f"{t.slug}: {type(exc).__name__}: {exc}")
                finally:
                    db.close()
        cp.commit()
    finally:
        cp.close()
    record(name, interval_seconds, ok=not errors, result=results, error="; ".join(errors) or None)


def schedule_all(scheduler) -> list[str]:
    """Adds every fan-out job of the Celery beat schedule to the in-app scheduler. The first run
    is a minute or two after start (staggered), so daily jobs don't wait a whole day after a restart."""
    from apscheduler.triggers.interval import IntervalTrigger

    from app.platform.jobs.scheduled import JOBS, celery_app

    added = []
    start = datetime.now(timezone.utc) + timedelta(seconds=60)
    for i, entry in enumerate(celery_app.conf.beat_schedule.values()):
        if entry.get("task") != "hrms.fan_out":
            continue
        name = entry["args"][0]
        if name not in JOBS:
            continue
        every = float(entry["schedule"])
        scheduler.add_job(run_job, trigger=IntervalTrigger(seconds=every), args=[name, every], id=f"job:{name}",
                          next_run_time=start + timedelta(seconds=15 * i), max_instances=1, coalesce=True)
        added.append(name)
    return added
