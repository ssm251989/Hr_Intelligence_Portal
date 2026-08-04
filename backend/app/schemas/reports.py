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
