import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class InterviewCreate(BaseModel):
    interviewer_id: Optional[uuid.UUID] = None
    scheduled_at: datetime
    meeting_link: Optional[str] = None


class InterviewFeedbackUpdate(BaseModel):
    technical_rating: Optional[int] = None
    communication_rating: Optional[int] = None
    overall_rating: Optional[int] = None
    comments: Optional[str] = None
    decision: Optional[Literal["selected", "rejected"]] = None


class InterviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    interviewer_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = None
    calendar_event_id: Optional[str] = None
    calendar_link: Optional[str] = None
    technical_rating: Optional[int] = None
    communication_rating: Optional[int] = None
    overall_rating: Optional[int] = None
    comments: Optional[str] = None
    decision: Optional[str] = None
    scheduling_method: str
    created_at: datetime


class InterviewQuestionsResponse(BaseModel):
    technical_questions: list[str]
    behavioral_questions: list[str]
    questions_to_probe_gaps: list[str]
