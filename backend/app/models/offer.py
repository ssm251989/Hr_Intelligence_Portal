from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            "onboarding_status IN ('not_started','in_progress','completed')",
            name="offers_onboarding_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    offer_letter_text = Column(Text)
    docusign_envelope_id = Column(String(255))
    signed = Column(Boolean, server_default=text("false"))
    onboarding_status = Column(String(50), server_default=text("'not_started'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
