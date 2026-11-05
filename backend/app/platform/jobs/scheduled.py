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


def _joining_reminders(db, tenant):
    from app.recruitment.joining_dates import remind_due

    return {"reminded": remind_due(db, tenant)}


def _recycle_bin_purge(db, tenant):
    from app.recruitment.removal import purge_expired

    return purge_expired(db, tenant)


def _joiner_exits(db, tenant):
    """fix 2026-10-05: "Not reporting" notices (reminder / show-cause / final) + logins of leavers off after their LWD."""
    from app.onboarding.joiner_actions import deactivate_after_lwd, run_not_reporting_notices

    return {"notices": run_not_reporting_notices(db, tenant), "logins_off": deactivate_after_lwd(db, tenant)}


def _exit_interview_reminders(db, tenant):
    """fix 2026-10-06: remind leavers to answer their exit interview N days before their last day."""
    from app.employees.exit_interview import run_reminders

    return {"reminders": run_reminders(db, tenant)}


def _exit_checklist(db, tenant):
    """feat 2026-10-06: exit checklist -- scheduled access revokes on the last day, owner reminders the day before due,
    exit completes by itself when everything is done and the last working day has passed."""
    from app.employees.exit_checklist import run_reminders

    return run_reminders(db, tenant)


def _interviewer_links(db, tenant):
    """Part 20.4: interviewers from the old Excel (availability rows) -> linked to employees by email, or an HR to-do."""
    from app.employees.interviewers import link_existing

    return link_existing(db, tenant)


def _closed_jobs_cleanup(db, tenant):
    """Part 21.1: closed jobs -> Recycle bin after N days; binned jobs past the time limit deleted permanently."""
    from app.jobs.cleanup import run_daily

    return run_daily(db, tenant)


def _hiring_data_after_exit(db, tenant):
    """Part 21.2: exits completed N days ago -> hiring data to the bin; binned exit data past the limit -> deleted."""
    from app.employees.hiring_on_exit import run_daily

    return run_daily(db, tenant)


def _bgv_vendor_reminders(db, tenant):
    """Part 21.4: remind BGV vendors the day before the due date and when overdue."""
    from app.bgv.vendors import run_reminders

    return run_reminders(db, tenant)


def _autopilot_events(db, tenant):
    """Part 26: HR Autopilot -- the automatic agents react to what just happened (audit-log events)."""
    from app.hr_agents.autopilot.runner import run_events

    return run_events(db, tenant)


def _autopilot_hourly(db, tenant):
    """Part 26: HR Autopilot -- watchdog, joining day, exit letters, morning briefing."""
    from app.hr_agents.autopilot.runner import run_hourly

    return run_hourly(db, tenant)


def _autopilot_daily(db, tenant):
    """Part 26: HR Autopilot -- sourcing for jobs with too few strong candidates."""
    from app.hr_agents.autopilot.runner import run_daily

    return run_daily(db, tenant)


JOBS = {
    "autopilot_events": _autopilot_events,
    "autopilot_hourly": _autopilot_hourly,
    "autopilot_daily": _autopilot_daily,
    "bgv_vendor_reminders": _bgv_vendor_reminders,
    "hiring_data_after_exit": _hiring_data_after_exit,
    "closed_jobs_cleanup": _closed_jobs_cleanup,
    "interviewer_links": _interviewer_links,
    "exit_checklist": _exit_checklist,
    "exit_interview_reminders": _exit_interview_reminders,
    "joiner_exits": _joiner_exits,
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
    "joining_reminders": _joining_reminders,
}


def _module_guard(job_name: str, fn):
    """Part 19.1: a job that belongs to a module (module_registry.JOB_MODULE) is skipped for a
    company that doesn't have that module active."""
    from app.platform import module_registry, module_status

    module = module_registry.JOB_MODULE.get(job_name)
    if module is None:
        return fn

    def guarded(db, tenant):
        if not module_status.is_active(db, tenant, module):
            return {"skipped": f"module {module} not active"}
        return fn(db, tenant)

    return guarded


@celery_app.task(base=TenantTask, name="hrms.run_tenant_job", bind=True, queue="low")
def run_tenant_job(self, job_name: str):
    result = _with_session(_module_guard(job_name, JOBS[job_name]))
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
@celery_app.task(name="hrms.activation_sweep", queue="default")
def activation_sweep() -> dict:
    """Part 19.2b/c: platform-level (not per company) -- retries + escalation of activation emails."""
    from app.platform.activation import sweep

    return sweep()


@celery_app.task(name="hrms.interview_automation", queue="default")
def interview_automation() -> dict:
    """fix 2026-10-04: undo-window release + mailbox retries for every company (heartbeat for Health)."""
    from app.interview_scheduling.automation import run_all_tenants

    return run_all_tenants("celery")


celery_app.conf.beat_schedule = {
    "autopilot-events": {"task": "hrms.fan_out", "schedule": 60.0, "args": ("autopilot_events",)},
    "autopilot-hourly": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("autopilot_hourly",)},
    "autopilot-daily": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("autopilot_daily",)},
    "activation-sweep": {"task": "hrms.activation_sweep", "schedule": 60.0},
    "interview-automation": {"task": "hrms.interview_automation", "schedule": 60.0},
    "workflow-timers": {"task": "hrms.fan_out", "schedule": 300.0, "args": ("workflow_timers",)},
    "ticket-escalations": {"task": "hrms.fan_out", "schedule": 300.0, "args": ("ticket_escalations",)},
    "report-schedules": {"task": "hrms.fan_out", "schedule": 600.0, "args": ("report_schedules",)},
    "review-reminders": {"task": "hrms.fan_out", "schedule": 21600.0, "args": ("review_reminders",)},
    "document-expiry": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("document_expiry",)},
    "privacy-overdue": {"task": "hrms.fan_out", "schedule": 21600.0, "args": ("privacy_overdue",)},
    "onboarding-chase": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("onboarding_chase",)},
    "salary-form-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("salary_form_reminders",)},
    "reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("reminders",)},
    "joining-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("joining_reminders",)},
    "documents-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("documents_reminders",)},
    "recycle-bin-purge": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("recycle_bin_purge",)},
    "joiner-exits": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("joiner_exits",)},
    "exit-interview-reminders": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("exit_interview_reminders",)},
    "exit-checklist": {"task": "hrms.fan_out", "schedule": 3600.0, "args": ("exit_checklist",)},
    "interviewer-links": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("interviewer_links",)},
    "closed-jobs-cleanup": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("closed_jobs_cleanup",)},
    "hiring-data-after-exit": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("hiring_data_after_exit",)},
    "bgv-vendor-reminders": {"task": "hrms.fan_out", "schedule": 86400.0, "args": ("bgv_vendor_reminders",)},
}
celery_app.conf.timezone = "UTC"
