import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.reports import LabeledCount, StatTrend

# Selected/Rejected are permanent once a decision is recorded; before that, an interview
# is Upcoming (still in the future) or Awaiting Feedback (its scheduled time has passed
# with no decision recorded yet). Shared vocabulary between the List page's Status filter,
# the dashboard's Recent Interviews table, and app/reports/stats.py's interview_status_case
# (the one place this is actually computed) so it's never defined two different ways.
INTERVIEW_STATUSES = ("upcoming", "awaiting_feedback", "selected", "rejected")


class InterviewListRow(BaseModel):
    """One interview, joined with its candidate/job/interviewer names -- the row shape
    shared by the Interview List page and the Interview Dashboard's Recent Interviews
    table, same pattern as CandidateApplicationRow's shared use across the Candidates
    List and Candidates Dashboard."""

    interview_id: uuid.UUID
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    job_role_id: uuid.UUID
    job_title: str
    interviewer_id: Optional[uuid.UUID] = None
    interviewer_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    scheduling_method: str
    status: str  # one of INTERVIEW_STATUSES
    decision: Optional[str] = None
    meeting_link: Optional[str] = None
    calendar_link: Optional[str] = None
    created_at: datetime


class InterviewsListPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[InterviewListRow]


class InterviewsDashboardStatsResponse(BaseModel):
    """The Interview Dashboard's stat cards + charts. total_interviews_scheduled_this_month
    is a real monthly count (created_at-windowed), same as the Jobs dashboard's
    hires_this_month. upcoming is a live backlog depth with no trend -- same caveat as
    Screening's awaiting_screening/awaiting_ranking: an interview's decision/occurred state
    isn't tracked historically, so there's no real past-month snapshot to compare against.
    completed/selected/rejected instead trend on an *approximate* cumulative-by-created_at
    basis (like Jobs dashboard's active_jobs/open_positions) -- current decision value,
    bucketed by when the interview row was created, not by when the decision itself was
    recorded (that timestamp isn't tracked either)."""

    total_interviews_scheduled_this_month: int
    upcoming: int
    completed: int
    selected: int
    rejected: int
    total_interviews_scheduled_this_month_trend: StatTrend
    completed_trend: StatTrend
    selected_trend: StatTrend
    rejected_trend: StatTrend
    outcome_breakdown: list[LabeledCount]
    interviewer_workload: list[LabeledCount]
    scheduling_method_breakdown: list[LabeledCount]
    recent_interviews: list[InterviewListRow]
