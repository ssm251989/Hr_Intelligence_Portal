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
    # Two distinct scores, deliberately both exposed rather than one silently replacing the
    # other: match_score is the original Resume Matcher score (app/ai_services/resume_matcher
    # .match_resume's own match_score), while composite_score is Part A's equal-weighted
    # composite across skills/experience/location/certificates/match_score -- the same number
    # Remarks' "Strong fit (score X)" text quotes (see app/screening/service.py
    # describe_screening_audit_entry). The Candidates List's "Screening Score" column shows
    # composite_score (falling back to match_score for applications screened before Part A
    # existed, which never got a composite_score); match_score is kept as a secondary detail
    # so the two numbers are never presented as the same thing under one column.
    match_score: Optional[float] = None
    composite_score: Optional[float] = None
    # skill_match_pct is one of the five composite_score inputs, surfaced on its own since
    # it's the single factor Remarks' "-- missing X, Y" text is directly about. ranking_score
    # is a later, separate step (the "Rank" action, app/screening/router.py rank_application)
    # -- null until an application has been ranked, independent of whether it's been screened.
    # Both needed by the Screening List page (Part E), which is where screen/rank decisions
    # actually get made.
    skill_match_pct: Optional[float] = None
    ranking_score: Optional[float] = None
    experience_years: Optional[float] = None
    resume_path: Optional[str] = None
    photo_path: Optional[str] = None
    inferred_gender: Optional[str] = None
    # "Suitable For" suggestion (Part B) -- the best-fitting published job this candidate
    # was automatically compared against, independent of the job_role_id/job_title above
    # (their actual applied-for job). All three null until a resume parse has found at
    # least one published job to compare against -- see app/screening/suitability.py.
    suitable_job_id: Optional[uuid.UUID] = None
    suitable_job_title: Optional[str] = None
    suitable_job_score: Optional[float] = None
    # Remarks (Part C) -- a rendering of this application's own latest ai_screening_scored/
    # ai_screening_failed audit_log entry (see app/screening/service.py
    # describe_screening_audit_entry), never a separately maintained string. Null until the
    # application has ever been screened.
    remarks: Optional[str] = None
    # Interview Readiness Remarks (Part F) -- a DIFFERENT rendering of that exact same
    # audit_log entry (see app/screening/service.py describe_interview_readiness), driven by
    # the separate interview_min_score threshold rather than dashboard_min_score. Shown as
    # the Screening List's own "Remarks" column; the Candidates List keeps showing `remarks`
    # above, unaffected. Null until the application has ever been screened.
    interview_remarks: Optional[str] = None


class CandidatesDashboardStatsResponse(BaseModel):
    total_candidates: int
    new_this_month: int
    from_career_portal: int
    manually_added: int
    active_candidates: int
    avg_match_score: Optional[float] = None
    total_candidates_trend: StatTrend
    new_this_month_trend: StatTrend
    from_career_portal_trend: StatTrend
    manually_added_trend: StatTrend
    avg_match_score_trend: StatTrend
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
