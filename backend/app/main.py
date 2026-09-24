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

register_tenant_owned_events(tenant_data_base)
install_tenant_read_filter()
register_settings_definitions()


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

# Part 2: resolves TenantContext for every request before any route or dependency runs
# (added last so it's the OUTERMOST middleware -- Starlette runs middlewares in reverse
# add order -- meaning tenant context is set before CORS or any router logic ever executes).
app.add_middleware(TenantResolverMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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


@app.get("/health")
def health():
    return {"status": "ok"}
