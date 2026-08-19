from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.bgv.router import router as bgv_router
from app.candidates.applications_router import router as applications_router
from app.candidates.router import router as candidates_router
from app.integrations.router import router as integrations_router
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


@app.get("/health")
def health():
    return {"status": "ok"}
