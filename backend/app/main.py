import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.bgv.router import router as bgv_router
from app.candidates.applications_router import router as applications_router
from app.candidates.router import router as candidates_router
from app.hr_inbox.router import router as hr_inbox_router
from app.integrations.router import router as integrations_router
from app.interview_scheduling.confirm_router import router as interview_confirm_router
from app.interview_scheduling.negotiation_router import router as interview_negotiation_router
from app.interview_scheduling.router import router as interview_scheduling_router
from app.jobs.router import router as jobs_router
from app.local_import.router import router as local_import_router
from app.local_import.scheduler import start_scheduler, stop_scheduler
from app.offers.router import router as offers_router
from app.public.router import router as public_router
from app.reports.router import router as reports_router
from app.salary.router import router as salary_router
from app.scheduling.router import router as scheduling_router
from app.screening.router import router as screening_router
from app.screening.router import settings_router as screening_settings_router
from app.shortlisting.router import router as shortlisting_router
from app.users.router import router as users_router
import app.models  # noqa: F401  -- registers every model (incl. TenantOwned ones) before the line below
from app.core.database import Base as tenant_data_base
from app.platform.tenancy.middleware import TenantResolverMiddleware
from app.platform.tenancy.mixins import install_tenant_read_filter, register_tenant_owned_events
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.settings.router import router as settings_router
from app.platform.secrets.router import router as secrets_router
from app.platform.connectors.api_router import (
    connections_router,
    router as connectors_router,
    routes_router as connection_routes_router,
)
from app.platform.comms.api_router import public_router as comms_public_router, router as comms_router
from app.platform.iam.api_router import router as iam_router
from app.platform.workflow.api_router import inbox_router as workflow_inbox_router, public_router as workflow_public_router, router as workflow_router
from app.platform.metadata.api_router import router as metadata_router
from app.platform.i18n.api_router import public_router as i18n_public_router, router as i18n_router
from app.platform.branding.api_router import public_router as branding_public_router, router as branding_router
from app.core_hr.api_router import public_router as core_hr_public_router, router as core_hr_router
from app.onboarding.api_router import public_router as onboarding_public_router, router as onboarding_router
from app.performance.api_router import router as performance_router
from app.service_desk.api_router import router as service_desk_router
from app.analytics.api_router import router as intelligence_router
from app.service_desk.tickets import register_inbound as register_helpdesk_inbound
from app.recruitment.api_router import public_router as recruitment_public_router, router as recruitment_router

register_tenant_owned_events(tenant_data_base)
install_tenant_read_filter()
register_settings_definitions()
register_helpdesk_inbound()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Part G: the scheduled local-import scan, interval configurable via local_import_
    # settings.scan_interval_minutes (app/local_import/scheduler.py) -- this app's first
    # background job, so this is also its first-ever lifespan hook. Single
    # dev process only: running multiple uvicorn workers would start one scheduler per
    # worker, all racing on the same ready_to_upload/ folder -- fine for this app's actual
    # deployment, not something this handles for a future multi-worker setup.
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="HR Automation", lifespan=lifespan)

# Part 13: added BEFORE TenantResolverMiddleware so they run INSIDE it (Starlette runs the
# last-added middleware outermost) -- rate limits and metrics need the resolved tenant.
from app.platform.ops.observability import ObservabilityMiddleware, configure_logging, init_optional_integrations  # noqa: E402
from app.platform.ops.rate_limit import RateLimitMiddleware  # noqa: E402
from app.platform.ops.security_headers import SecurityHeadersMiddleware  # noqa: E402

configure_logging()
init_optional_integrations(app)
from app.platform.activation import check_startup as _check_activation  # noqa: E402

_check_activation()  # Part 19.2: refuse to start with an activation approver outside ctdtechs.com
app.add_middleware(RateLimitMiddleware)
from app.platform.modules import ModuleGateMiddleware  # noqa: E402
from app.platform.module_status import ModuleActivationMiddleware  # noqa: E402
from app.platform.ops.idempotency import IdempotencyMiddleware  # noqa: E402

app.add_middleware(IdempotencyMiddleware)  # Part 17.13: inside the tenant resolver (needs the tenant)

app.add_middleware(ModuleGateMiddleware)
app.add_middleware(ModuleActivationMiddleware)  # Part 19.1: module not active for this company -> 403 (inside the tenant resolver)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Part 2: resolves TenantContext for every request before any route or dependency runs
# (added last so it's the OUTERMOST middleware -- Starlette runs middlewares in reverse
# add order -- meaning tenant context is set before CORS or any router logic ever executes).
app.add_middleware(TenantResolverMiddleware)

from app.experience.errors import cors_origins  # noqa: E402 -- shared with the 500 handler

app.add_middleware(
    CORSMiddleware,
    # Part 13: per-installation list (CORS_ORIGINS, comma-separated); dev default unchanged.
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(candidates_router)
app.include_router(applications_router)
app.include_router(screening_router)
app.include_router(screening_settings_router)
app.include_router(shortlisting_router)
app.include_router(scheduling_router)
app.include_router(salary_router)
app.include_router(bgv_router)
app.include_router(offers_router)
app.include_router(reports_router)
app.include_router(integrations_router)
app.include_router(users_router)
app.include_router(public_router)
app.include_router(local_import_router)
app.include_router(interview_scheduling_router)
app.include_router(interview_confirm_router)
app.include_router(interview_negotiation_router)
app.include_router(hr_inbox_router)
app.include_router(settings_router)
app.include_router(secrets_router)
app.include_router(connectors_router)
app.include_router(connections_router)
app.include_router(connection_routes_router)
app.include_router(comms_router)
app.include_router(comms_public_router)
app.include_router(iam_router)
app.include_router(workflow_router)
app.include_router(workflow_inbox_router)
app.include_router(workflow_public_router)
app.include_router(metadata_router)
app.include_router(i18n_router)
app.include_router(i18n_public_router)
app.include_router(branding_router)
app.include_router(branding_public_router)
app.include_router(core_hr_router)
app.include_router(core_hr_public_router)
app.include_router(recruitment_router)
app.include_router(recruitment_public_router)
app.include_router(onboarding_router)
app.include_router(onboarding_public_router)
app.include_router(performance_router)
app.include_router(service_desk_router)
app.include_router(intelligence_router)


from app.platform.ops.health import router as ops_router  # noqa: E402
from app.superadmin.router import router as superadmin_router  # noqa: E402
from app.privacy.api_router import public_router as privacy_public_router, router as privacy_router  # noqa: E402
from app.experience.api_router import router as experience_router  # noqa: E402
from app.experience.errors import install as install_friendly_errors  # noqa: E402

app.include_router(ops_router)
app.include_router(superadmin_router)
app.include_router(privacy_router)
app.include_router(privacy_public_router)
app.include_router(experience_router)
from app.experience.media_router import router as media_router  # noqa: E402

app.include_router(media_router)
from app.experience.home_router import router as home_router  # noqa: E402

app.include_router(home_router)
from app.experience.ui_offers_router import router as ui_offers_router  # noqa: E402

app.include_router(ui_offers_router)
from app.experience.ui_interviews_router import router as ui_interviews_router  # noqa: E402

app.include_router(ui_interviews_router)
from app.experience.ui_jobs_router import router as ui_jobs_router  # noqa: E402

app.include_router(ui_jobs_router)
from app.experience.ui_candidates_router import router as ui_candidates_router  # noqa: E402

app.include_router(ui_candidates_router)
from app.experience.ui_screening_router import router as ui_screening_router  # noqa: E402

app.include_router(ui_screening_router)
from app.experience.ui_careers_router import router as ui_careers_router  # noqa: E402

app.include_router(ui_careers_router)
from app.experience.settings_home_router import router as settings_home_router  # noqa: E402

app.include_router(settings_home_router)
from app.experience.ui_people_router import router as ui_people_router  # noqa: E402

app.include_router(ui_people_router)
from app.experience.modules_router import router as modules_router  # noqa: E402 -- Part 19.1/19.2

app.include_router(modules_router)
from app.experience.ui_jd_screening_router import router as ui_jd_screening_router  # noqa: E402 -- Part 19.1

app.include_router(ui_jd_screening_router)
from app.experience.ui_onboarding_router import router as ui_onboarding_router  # noqa: E402

app.include_router(ui_onboarding_router)
from app.experience.ui_performance_router import router as ui_performance_router  # noqa: E402

app.include_router(ui_performance_router)
from app.experience.ui_servicedesk_router import router as ui_servicedesk_router  # noqa: E402

app.include_router(ui_servicedesk_router)
from app.experience.ui_insights_router import router as ui_insights_router  # noqa: E402

app.include_router(ui_insights_router)
from app.experience.ui_onboarding_router import public_router as ui_onboarding_public_router  # noqa: E402

app.include_router(ui_onboarding_public_router)
from app.recruitment.agency_router import portal_router as agency_portal_router, router as agency_router  # noqa: E402

app.include_router(agency_router)
app.include_router(agency_portal_router)
from app.experience.geo_router import router as geo_router  # noqa: E402

app.include_router(geo_router)
from app.recruitment.scoring.api_router import router as scoring_router  # noqa: E402

app.include_router(scoring_router)
from app.experience.ui_salary_router import public_router as salary_form_router, router as ui_salary_router  # noqa: E402

app.include_router(ui_salary_router)
app.include_router(salary_form_router)
from app.experience.ui_candidate_emails_router import router as candidate_emails_router  # noqa: E402

app.include_router(candidate_emails_router)
from app.experience.ui_interviewers_router import router as ui_interviewers_router  # noqa: E402

app.include_router(ui_interviewers_router)
from app.experience.ui_automation_router import public_router as status_public_router, router as ui_automation_router  # noqa: E402

app.include_router(ui_automation_router)
app.include_router(status_public_router)
from app.experience.ui_candidate_removal_router import router as ui_candidate_removal_router  # noqa: E402

app.include_router(ui_candidate_removal_router)

from app.experience.ui_job_boards_router import router as ui_job_boards_router  # noqa: E402

app.include_router(ui_job_boards_router)
from app.experience.ui_stage_table_router import router as ui_stage_table_router  # noqa: E402

app.include_router(ui_stage_table_router)
from app.experience.ui_budgets_router import router as ui_budgets_router  # noqa: E402

app.include_router(ui_budgets_router)
from app.experience.ui_documents_router import public_router as documents_public_router, router as ui_documents_router  # noqa: E402

app.include_router(ui_documents_router)
app.include_router(documents_public_router)
from app.experience.ui_documents_router import bgv_router as ui_bgv_decision_router  # noqa: E402

app.include_router(ui_bgv_decision_router)
from app.experience.ui_documents_router import joining_public_router, joining_router  # noqa: E402

app.include_router(joining_router)
app.include_router(joining_public_router)
from app.experience.ui_users_router import router as ui_users_router  # noqa: E402

app.include_router(ui_users_router)
from app.experience.ui_genai_router import router as ui_genai_router  # noqa: E402

app.include_router(ui_genai_router)
install_friendly_errors(app)


@app.get("/health")
def health():
    return {"status": "ok"}
