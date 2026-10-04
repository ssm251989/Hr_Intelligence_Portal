"""Part 17.13: one health page for admins -- database, mailbox, AI, storage, background jobs.
Each check -> {key, status: green | amber | red, message, checked_at, detail}. Checks are live
and cheap (no email is sent, no AI call is made); results are cached for 60 seconds.
"""

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 60


def _item(key: str, status: str, message: str, **detail) -> dict:
    return {"key": key, "status": status, "message": message, "checked_at": datetime.now(timezone.utc).isoformat(), "detail": detail}


def _database(db: Session) -> dict:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return _item("database", "red", "The database can't be reached.", error=str(exc)[:200])
    ms = round((time.perf_counter() - started) * 1000)
    return _item("database", "green" if ms < 250 else "amber", f"Database answers in {ms} ms.", ms=ms)


def _mailbox(db: Session, tenant) -> dict:
    from app.experience.setup_wizard import _mailbox_state
    from app.models.comms import OutboundMessage

    ok, detail = _mailbox_state(db, tenant)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = dict(db.query(OutboundMessage.status, func.count(OutboundMessage.id))
                .filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.channel == "email", OutboundMessage.created_at >= since)
                .group_by(OutboundMessage.status).all())
    failed, sent = rows.get("failed", 0), rows.get("sent", 0) + rows.get("queued", 0)
    if not ok:
        return _item("mailbox", "red", detail, sent_24h=sent, failed_24h=failed)
    if failed and failed >= max(3, sent):
        return _item("mailbox", "amber", f"{failed} emails failed in the last 24 hours.", sent_24h=sent, failed_24h=failed)
    return _item("mailbox", "green", f"Mailbox connected. {sent} emails sent in the last 24 hours.", sent_24h=sent, failed_24h=failed)


def _ai(db: Session, tenant) -> dict:
    from app.models.intelligence import AiDecisionLog
    from app.platform.connectors.router import ConnectorRouter
    from app.platform.settings.resolver import SettingContext, SettingsService

    if not SettingsService(db).get("ai.enabled", SettingContext(tenant=tenant)):
        return _item("ai", "amber", "AI is switched off for your company.")
    if ConnectorRouter(db).try_resolve("llm.scoring") is None and ConnectorRouter(db).try_resolve("llm.judgment") is None:
        return _item("ai", "red", "AI is on but no AI connection is set up.")
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = dict(db.query(AiDecisionLog.status, func.count(AiDecisionLog.id)).filter(AiDecisionLog.tenant_id == tenant.tenant_id,
                                                                                 AiDecisionLog.created_at >= since).group_by(AiDecisionLog.status).all())
    errors = rows.get("error", 0) + rows.get("failed", 0)
    total = sum(rows.values())
    if total and errors / total > 0.2:
        return _item("ai", "amber", f"{errors} of {total} AI calls failed in the last 24 hours.", calls_24h=total, errors_24h=errors)
    return _item("ai", "green", f"AI connected. {total} AI calls in the last 24 hours.", calls_24h=total, errors_24h=errors)


def _storage() -> dict:
    from app.experience.media_router import MEDIA_DIR, _storage as storage_adapter

    adapter = storage_adapter()
    if adapter is not None:
        try:
            res = adapter.health_check()
            return _item("storage", "green" if res.success else "red", "Storage connection works." if res.success else f"Storage connection failed: {res.error}")
        except Exception as exc:  # noqa: BLE001
            return _item("storage", "red", f"Storage connection failed: {exc}"[:200])
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        probe = MEDIA_DIR / ".health"
        probe.write_text("ok")
        probe.unlink()
        return _item("storage", "amber", "Files are kept on this server's disk. Connect cloud storage for backups and scale.", where=str(MEDIA_DIR))
    except OSError as exc:
        return _item("storage", "red", f"Files can't be saved: {exc}"[:200])


JOB_LABELS = {
    "interview_automation": "Interview times after shortlist (undo window, email retries)",
    "activation_sweep": "Activation emails (retries, escalation)",
    "salary_form_reminders": "Salary form reminders (24 h)", "reminders": "Reminders", "documents_reminders": "Document reminders",
    "joining_reminders": "Joining reminders", "workflow_timers": "Approval timers", "report_schedules": "Scheduled reports",
    "onboarding_chase": "Onboarding document chase", "recycle_bin_purge": "Recycle bin clean-up", "document_expiry": "Document expiry",
    "privacy_overdue": "Privacy requests due", "ticket_escalations": "Helpdesk escalations", "review_reminders": "Review reminders",
}


def _jobs(db: Session, tenant) -> dict:
    """Owner 2026-10-04: green / red with the last run of every background job. Locally the backend
    runs them itself (JOBS_IN_APP); with a Celery worker, the worker does."""
    from app.core.config import settings

    if settings.JOBS_IN_APP:
        from app.platform.jobs.inapp import status

        now = datetime.now(timezone.utc)
        rows, late = [], []
        for name, st in sorted(status().items()):
            age = (now - datetime.fromisoformat(st["last_run"])).total_seconds()
            on_time = age <= 2 * float(st.get("every_seconds") or 60) + 600
            ok = bool(st.get("ok")) and on_time
            rows.append({"job": name, "label": JOB_LABELS.get(name, name), "last_run": st["last_run"], "ok": ok, "error": st.get("error"),
                         "state": "ok" if ok else ("failed" if not st.get("ok") else "late")})
            if not ok:
                late.append(JOB_LABELS.get(name, name))
        expected = set(JOB_LABELS) - {"ticket_escalations", "review_reminders"}  # helpdesk / performance modules may be off
        never = sorted(JOB_LABELS[j] for j in expected - {r["job"] for r in rows})
        if not rows:
            return _item("jobs", "red", "Background jobs haven't run yet. Restart the backend; they start a minute after it starts.", jobs=[])
        if late or never:
            parts = []
            if late:
                parts.append("not on time or failing: " + ", ".join(late))
            if never:
                parts.append("not run yet: " + ", ".join(never))
            return _item("jobs", "red", "Some background jobs need attention - " + "; ".join(parts) + ".", jobs=rows, runner="backend (in-app)")
        last = max(r["last_run"] for r in rows)
        return _item("jobs", "green", f"All {len(rows)} background jobs are running inside the backend (last run {last[11:16]} UTC).", jobs=rows, runner="backend (in-app)")
    if not settings.REDIS_URL:
        return _item("jobs", "red", "No background worker: JOBS_IN_APP is off and there is no REDIS_URL, so reminders and scheduled emails don't run. "
                     "Turn JOBS_IN_APP on (default) or start the worker (see docs/RESUME.txt).")
    try:
        import redis
    except ImportError:
        return _item("jobs", "amber", "The background worker's queue client isn't installed on this server.")
    try:
        redis.from_url(settings.REDIS_URL, socket_timeout=2).ping()
    except Exception as exc:  # noqa: BLE001
        return _item("jobs", "red", "The background job queue can't be reached.", error=str(exc)[:200])
    return _item("jobs", "green", "Background jobs run on the worker (Celery).")


def _links(db: Session) -> dict:
    """fix 2026-10-04: links in emails must open for the people who get them."""
    from app.platform.links import is_local, public_app_url, public_base_url

    base, app_url = public_base_url(db), public_app_url(db)
    local = [u for u in (base, app_url) if is_local(u)]
    if local:
        return _item("links", "amber", f"Links in emails point to {' and '.join(local)} - they only open on this computer, so candidates and interviewers "
                     "elsewhere can't open them. Set both public addresses in Settings > Company > Profile.", base=base, app=app_url)
    return _item("links", "green", f"Links in emails use {base} (server) and {app_url} (web app).", base=base, app=app_url)


def check(db: Session, tenant, *, fresh: bool = False) -> dict:
    key = str(tenant.tenant_id)
    hit = _CACHE.get(key)
    if hit and not fresh and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    items = []
    for fn in (lambda: _database(db), lambda: _mailbox(db, tenant), lambda: _ai(db, tenant), _storage, lambda: _jobs(db, tenant), lambda: _links(db)):
        try:
            items.append(fn())
        except Exception as exc:  # noqa: BLE001 -- one broken check never hides the others
            items.append(_item("check", "red", f"This check failed: {exc}"[:200]))
    worst = "red" if any(i["status"] == "red" for i in items) else "amber" if any(i["status"] == "amber" for i in items) else "green"
    result = {"overall": worst, "items": items, "checked_at": datetime.now(timezone.utc).isoformat()}
    _CACHE[key] = (time.time(), result)
    return result
