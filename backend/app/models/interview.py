from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('selected','rejected')",
            name="interviews_decision_check",
        ),
        CheckConstraint(
            "scheduling_method IN ('manual','auto')",
            name="interviews_scheduling_method_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    interviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    scheduled_at = Column(DateTime(timezone=True))
    meeting_link = Column(Text)
    calendar_event_id = Column(String(255))
    calendar_link = Column(Text)
    technical_rating = Column(Integer)
    communication_rating = Column(Integer)
    overall_rating = Column(Integer)
    comments = Column(Text)
    decision = Column(String(20))
    # "manual" = the recruiter-driven POST /applications/{id}/interviews flow
    # (app/scheduling/router.py); "auto" = Part 3's candidate email + secure-link
    # confirmation flow (app/interview_scheduling/confirmation.py confirm_token). Defaults
    # to "manual" so every row created before this column existed backfills correctly --
    # the auto flow is new and didn't exist when any of those rows were created.
    scheduling_method = Column(String(20), nullable=False, server_default=text("'manual'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
