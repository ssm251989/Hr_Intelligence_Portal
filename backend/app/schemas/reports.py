import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class StatusCount(BaseModel):
    status: str
    count: int


class PipelineResponse(BaseModel):
    total: int
    by_status: list[StatusCount]


class JobSummaryResponse(BaseModel):
    job_role_id: uuid.UUID
    total_applications: int
    by_status: list[StatusCount]
    average_match_score: Optional[float] = None
    average_ranking_score: Optional[float] = None


class LabeledCount(BaseModel):
    label: str
    count: int


class TopJobItem(BaseModel):
    job_id: uuid.UUID
    title: str
    application_count: int


class JobsDashboardStatsResponse(BaseModel):
    total_jobs: int
    active_jobs: int
    open_positions: int
    total_applications: int
    hires_this_month: int
    avg_time_to_hire_days: Optional[float] = None
    by_department: list[LabeledCount]
    by_location: list[LabeledCount]
    top_jobs: list[TopJobItem]


class RecentActivityItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    message: str
    entity_type: Optional[str] = None
    entity_id: Optional[uuid.UUID] = None


class RecentActivityResponse(BaseModel):
    items: list[RecentActivityItem]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: Optional[str] = None
    entity_id: Optional[uuid.UUID] = None
    action: Optional[str] = None
    actor: Optional[str] = None
    details: Optional[dict] = None
    created_at: datetime


class AuditLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditLogRead]


class ApplicationTimelineResponse(BaseModel):
    application_id: uuid.UUID
    events: list[AuditLogRead]
