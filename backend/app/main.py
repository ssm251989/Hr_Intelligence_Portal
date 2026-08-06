from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.bgv.router import router as bgv_router
from app.candidates.applications_router import router as applications_router
from app.candidates.router import router as candidates_router
from app.integrations.router import router as integrations_router
from app.jobs.router import router as jobs_router
from app.offers.router import router as offers_router
from app.public.router import router as public_router
from app.reports.router import router as reports_router
from app.salary.router import router as salary_router
from app.scheduling.router import router as scheduling_router
from app.screening.router import router as screening_router
from app.shortlisting.router import router as shortlisting_router
from app.users.router import router as users_router

app = FastAPI(title="HR Automation")

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
app.include_router(shortlisting_router)
app.include_router(scheduling_router)
app.include_router(salary_router)
app.include_router(bgv_router)
app.include_router(offers_router)
app.include_router(reports_router)
app.include_router(integrations_router)
app.include_router(users_router)
app.include_router(public_router)


@app.get("/health")
def health():
    return {"status": "ok"}
