from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.reports import LabeledCount, StatTrend


class ScreeningSettingsRead(BaseModel):
    """Part 17.4: the one company-level Shortlist threshold (0-100 Match score)."""

    shortlist_threshold: float
    updated_at: Optional[datetime] = None


class ScreeningSettingsUpdate(BaseModel):
    shortlist_threshold: float = Field(..., ge=0, le=100)


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
