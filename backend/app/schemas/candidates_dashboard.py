import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.application import ApplicationRead
from app.schemas.candidate import CandidateRead
from app.schemas.reports import LabeledCount, StatTrend


class CandidateDataSourceStatus(BaseModel):
    """Real connection status for one candidate-sourcing channel -- never a decorative
    "connected" badge. LinkedIn/Naukri have no real candidate-import access today (the
    LinkedIn integration elsewhere in this app only grants job-posting, not candidate
    import), so they always report connected=False here."""

    source: str
    label: str
    connected: bool
    last_sync: Optional[datetime] = None


class CandidateApplicationRow(BaseModel):
    """One (candidate, application) pairing -- the row shape shared by the dashboard's
    Recent Candidates table, the full Candidates List page, and a candidate's list of
    other applications on their detail page. A candidate with N applications appears as
    N separate rows across the list/dashboard, one per job."""

    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    job_role_id: uuid.UUID
    job_title: str
    status: str
    source: str
    location: Optional[str] = None
    applied_on: datetime
    match_score: Optional[float] = None
    experience_years: Optional[float] = None
    resume_path: Optional[str] = None


class CandidatesDashboardStatsResponse(BaseModel):
    total_candidates: int
    new_this_month: int
    from_career_portal: int
    manually_added: int
    active_candidates: int
    total_candidates_trend: StatTrend
    new_this_month_trend: StatTrend
    by_source: list[LabeledCount]
    top_skills: list[LabeledCount]
    match_score_distribution: list[LabeledCount]
    data_sources: list[CandidateDataSourceStatus]
    recent_candidates: list[CandidateApplicationRow]


class CandidatesListPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CandidateApplicationRow]


class NextAction(BaseModel):
    """A shortcut into an application's real pipeline endpoints -- never a status
    bypass. `kind="one_click"` actions carry everything needed to call the existing
    endpoint directly (method/endpoint/body); `kind="navigate"` actions instead point the
    recruiter at the existing page that already collects the extra input that transition
    needs (an interview slot, a salary amount, BGV documents)."""

    key: str
    label: str
    kind: Literal["one_click", "navigate"]
    method: Optional[str] = None
    endpoint: Optional[str] = None
    body: Optional[dict] = None
    route: Optional[str] = None
    confirm: bool = False
    description: Optional[str] = None


class OtherApplicationItem(BaseModel):
    application_id: uuid.UUID
    job_role_id: uuid.UUID
    job_title: str
    status: str
    applied_on: datetime


class CandidateApplicationDetail(BaseModel):
    application: ApplicationRead
    job_title: str
    candidate: CandidateRead
    next_actions: list[NextAction]
    other_applications: list[OtherApplicationItem]


class CandidateMessageRequest(BaseModel):
    subject: str
    body: str


class CandidateMessageResponse(BaseModel):
    sent: bool
    to: str


class CsvImportRowError(BaseModel):
    row: int
    reason: str


class CsvImportSummary(BaseModel):
    imported: int
    skipped: int
    errors: list[CsvImportRowError]
    imported_candidate_ids: list[uuid.UUID]
