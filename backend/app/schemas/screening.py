from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.reports import LabeledCount, StatTrend


class ScreeningSettingsRead(BaseModel):
    dashboard_min_score: float
    dashboard_max_score: float
    interview_min_score: float
    interview_max_score: float
    updated_at: Optional[datetime] = None


class ScreeningSettingsUpdate(BaseModel):
    """Two independent threshold pairs on the one settings row, each saveable on its own:
    the Candidates Dashboard's auto-advance threshold form (Part D, dashboard_min/max_score)
    and the Screening Dashboard's interview-readiness threshold form (Part F,
    interview_min/max_score). Either pair may be omitted entirely -- whichever pair a
    request DOES send must be sent together (a lone min or max is meaningless for a range)
    and the other pair, if present in the current row, is left untouched. Applies to every
    screening call (new uploads and Re-evaluate All alike) from the moment it's saved, since
    run_screening always reads the current screening_settings row rather than a value
    cached at some earlier point."""

    dashboard_min_score: Optional[float] = Field(None, ge=0, le=100)
    dashboard_max_score: Optional[float] = Field(None, ge=0, le=100)
    interview_min_score: Optional[float] = Field(None, ge=0, le=100)
    interview_max_score: Optional[float] = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _validate_pairs(self) -> "ScreeningSettingsUpdate":
        if (self.dashboard_min_score is None) != (self.dashboard_max_score is None):
            raise ValueError("dashboard_min_score and dashboard_max_score must be provided together")
        if (self.interview_min_score is None) != (self.interview_max_score is None):
            raise ValueError("interview_min_score and interview_max_score must be provided together")
        if self.dashboard_min_score is not None and self.dashboard_min_score > self.dashboard_max_score:
            raise ValueError("dashboard_min_score must be less than or equal to dashboard_max_score")
        if self.interview_min_score is not None and self.interview_min_score > self.interview_max_score:
            raise ValueError("interview_min_score must be less than or equal to interview_max_score")
        if self.dashboard_min_score is None and self.interview_min_score is None:
            raise ValueError("Provide at least one threshold pair (dashboard_min/max_score or interview_min/max_score)")
        return self


class ReEvaluateAllResult(BaseModel):
    """Summary counts for one Re-evaluate All run (Part D) -- returned rather than the
    full list of affected applications so the dashboard can show a plain confirmation
    toast without needing to render a report."""

    considered: int
    skipped_already_decided: int
    updated: int
    advanced_to_screened: int
    not_ready: int
    failed: int


class ScreeningDashboardStatsResponse(BaseModel):
    """Part E: the Screening Dashboard's stat cards + charts. awaiting_screening/
    awaiting_ranking are live backlog depths (no trend -- see stats.awaiting_screening_count);
    everything else follows the same monthly-trend shape as the Candidates/Jobs dashboards."""

    awaiting_screening: int
    awaiting_ranking: int
    auto_advanced_this_month: int
    failed_this_month: int
    avg_composite_score: Optional[float] = None
    auto_advanced_this_month_trend: StatTrend
    failed_this_month_trend: StatTrend
    avg_composite_score_trend: StatTrend
    recommendation_breakdown: list[LabeledCount]
    composite_score_distribution: list[LabeledCount]
    top_missing_skills: list[LabeledCount]
