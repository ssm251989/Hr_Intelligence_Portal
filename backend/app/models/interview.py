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
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    interviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    scheduled_at = Column(DateTime(timezone=True))
    meeting_link = Column(Text)
    technical_rating = Column(Integer)
    communication_rating = Column(Integer)
    overall_rating = Column(Integer)
    comments = Column(Text)
    decision = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
