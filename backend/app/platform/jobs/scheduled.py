"""Periodic jobs (docs/HRMS_COMPLETE_SPEC.txt Part 2 section C "celery beat -> per-tenant",
Part 13 section C). Closes the "needs a live scheduler" gap Parts 2/4/5/7/9-12 documented:
beat fires ONE fan-out task per job, which dispatches a per-tenant TenantTask for every
active tenant (so each run has its own TenantContext, RLS scope and noisy-tenant slot).

Every job body is an already-existing, already-callable service function -- this module
only schedules them. Purges are deliberately NOT scheduled: retention runs need a human
approval between dry-run and execute (Part 13 section E).
"""

import logging

import app.models  # noqa: F401 -- a worker process never imports app.main, so register models + tenant hooks here
from app.core.database import Base
from app.platform.jobs.celery_app import celery_app
from app.platform.settings.bootstrap_definitions import register_all as _register_settings
from app.platform.tenancy.mixins import install_tenant_read_filter, register_tenant_owned_events

register_tenant_owned_events(Base)
install_tenant_read_filter()
_register_settings()
from app.platform.jobs.tenant_task import TenantTask, apply_for_tenant

log = logging.getLogger(__name__)


def _with_session(fn):
    from app.core.database import SessionLocal
    from app.platform.tenancy.context import get_current_tenant

    db = SessionLocal()
    try:
        return fn(db, get_current_tenant())
    finally:
        db.close()


def _workflow_timers(db, tenant):
    from app.platform.workflow.engine import process_due_timers

    return process_due_timers(db, tenant)


def _ticket_escalations(db, tenant):
    from app.service_desk.tickets import process_escalations

    return process_escalations(db, tenant)


def _report_schedules(db, tenant):
    from app.analytics.schedules import run_due_schedules

    return len(run_due_schedules(db, tenant))


def _review_reminders(db, tenant):
    from app.models.performance import ReviewCycle
    from app.performance.reviews import send_due_reminders

    return sum(send_due_reminders(db, tenant, c) for c in db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tenant.tenant_id, ReviewCycle.status == "active").all())


def _document_expiry(db, tenant):
    from app.core_hr.documents import check_expiring_documents

    result = check_expiring_documents(db, tenant)
    return len(result) if hasattr(result, "__len__") else result


def _privacy_overdue(db, tenant):
    from app.platform.comms.service import dispatch_event
    from app.privacy.service import overdue_requests

    overdue = overdue_requests(db, tenant)
    for request in overdue:
        dispatch_event(db, tenant, "privacy.request_overdue", {"request_id": str(request.id), "type": request.request_type, "due_at": request.due_at.isoformat()})
    return len(overdue)


def _onboarding_chase(db, tenant):
    from app.agents.service import onboarding_chase_documents
    from app.platform.ai.governance import AIDisabledError

    try:
        return len(onboarding_chase_documents(db, tenant))
    except AIDisabledError:
        return 0


def _auto_shortlist_release(db, tenant):
    from app.recruitment.scoring.autoshortlist import release_due

    return release_due(db, tenant)


def _salary_form_reminders(db, tenant):
    from app.recruitment.salary_auto import remind_due

    return remind_due(db, tenant)


def _reminders(db, tenant):
    from app.recruitment.automation import send_reminders

    return send_reminders(db, tenant)


def _documents_reminders(db, tenant):
    from app.recruitment.joining_docs import remind_due

    return {"reminded": remind_due(db, tenant)}


def _recycle_bin_purge(db, tenant):
    from app.recruitment.removal import purge_expired

    return purge_expired(db, tenant)


JOBS = {
    "workflow_timers": _workflow_timers,
    "ticket_escalations": _ticket_escalations,
    "report_schedules": _report_schedules,
    "review_reminders": _review_reminders,
    "document_expiry": _document_expiry,
    "privacy_overdue": _privacy_overdue,
    "onboarding_chase": _onboarding_chase,
    "auto_shortlist_release": _auto_shortlist_release,
    "salary_form_reminders": _salary_form_reminders,
    "reminders": _reminders,
    "recycle_bin_purge": _recycle_bin_purge,
    "documents_reminders": _documents_reminders,
}


@celery_app.task(base=TenantTask, name="hrms.run_tenant_job", bind=True, queue="low")
def run_tenant_job(self, job_name: str):
    result = _with_session(JOBS[job_name])
    log.info("job %s done: %s", job_name, result)
    return result


@celery_app.task(name="hrms.fan_out", queue="default")
def fan_out(job_name: str) -> int:
    """Dispatches `job_name` once per active tenant."""
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant

    if job_name not in JOBS:
        raise KeyError(job_name)
    cp_db = ControlPlaneSessionLocal()
    try:
        tenant_ids = [t.id for t in cp_db.query(Tenant).filter(Tenant.status == "active").all()]
    finally:
        cp_db.close()
    for tenant_id in tenant_ids:
        apply_for_tenant(run_tenant_job, tenant_id, job_name)
    return len(tenant_ids)


# Beat schedule (seconds). Tenant-local timing (e.g. report delivery hour) is handled
# inside each job against the tenant's own timezone; beat only sets the polling cadence.
celery_app.conf.beat_schedule = {
    "workflow-timers": {"task": "hrms.fan_out", "schedule": 300.0, "args": ("workflow_timers",)},
    "ticket-escalations": {"task": "hrms.fan_out", "schedule": 300.0, "args": ("ticket_escalations",)},
    "report-schedules": {"task": "hrms.fan_out", "schedule": 600.0, "args": ("report_schedules",)},
    "review-reminders": {"task": "hrms.fan_out", "schedule": 21600.0, "args": ("review_reminders",)},
    "document-expiry": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("document_expiry",)},
    "privacy-overdue": {"task": "hrms.fan_out", "schedule": 21600.0, "args": ("privacy_overdue",)},
    "onboarding-chase": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("onboarding_chase",)},
    "auto-shortlist-release": {"task": "hrms.fan_out", "schedule": 300.0, "args": ("auto_shortlist_release",)},
    "salary-form-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("salary_form_reminders",)},
    "reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("reminders",)},
    "documents-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("documents_reminders",)},
    "recycle-bin-purge": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("recycle_bin_purge",)},
}
celery_app.conf.timezone = "UTC"
