import uuid
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.candidates_dashboard import CandidateApplicationRow
from app.schemas.reports import LabeledCount, StatTrend


class ShortlistFunnelStage(BaseModel):
    label: str
    count: int


class ShortlistingDashboardStatsResponse(BaseModel):
    # Live backlog depth (Under Review) -- no trend, same as awaiting_screening/
    # awaiting_ranking on the Screening Dashboard: an application's status isn't tracked
    # historically, so there's no past-month snapshot to compare against.
    total_in_shortlisting: int
    new_this_month: int
    moved_from_screening_this_month: int
    shortlisted_this_month: int
    avg_composite_score_shortlisted: Optional[float] = None
    new_this_month_trend: StatTrend
    moved_from_screening_this_month_trend: StatTrend
    shortlisted_this_month_trend: StatTrend
    avg_composite_score_shortlisted_trend: StatTrend
    funnel: list[ShortlistFunnelStage]
    composite_score_distribution: list[LabeledCount]
    # Plain sentences, each traceable to one real query (see reports/router.py
    # _shortlisting_insights) -- never AI-generated or hand-authored copy.
    insights: list[str]
    recent_shortlisted: list[CandidateApplicationRow]


class ShortlistStatusUpdateRequest(BaseModel):
    target_status: Literal["under_review", "shortlisted", "on_hold", "not_shortlisted"]
    reason: Optional[str] = None
    feedback: Optional[str] = None


class ShortlistFeedbackSuggestionResponse(BaseModel):
    suggested_feedback: str


class ShortlistBulkDecisionRequest(BaseModel):
    """The bulk counterpart to ShortlistStatusUpdateRequest -- deliberately restricted to
    the two terminal decisions (the List page's "Shortlist Selected"/"Reject Selected"
    buttons); on_hold/under_review aren't bulk actions here. reason/feedback, when given,
    are applied identically to every application in the batch -- per-candidate feedback can
    still be edited individually afterward on their own detail page."""

    application_ids: list[uuid.UUID]
    target_status: Literal["shortlisted", "not_shortlisted"]
    reason: Optional[str] = None
    feedback: Optional[str] = None


class ShortlistBulkDecisionSkipped(BaseModel):
    application_id: uuid.UUID
    reason: str


class ShortlistBulkDecisionResult(BaseModel):
    succeeded: list[uuid.UUID]
    skipped: list[ShortlistBulkDecisionSkipped]
