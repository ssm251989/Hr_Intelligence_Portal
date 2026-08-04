from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

APPLICATION_STATUSES = (
    "received", "screened", "hr_selected", "hr_rejected",
    "interview_scheduled", "interview_selected", "interview_rejected",
    "salary_ok", "salary_above_band", "salary_approved", "salary_rejected",
    "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected",
    "offer_sent", "onboarding_started", "onboarding_completed",
)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in APPLICATION_STATUSES) + ")",
            name="applications_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"))
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"))
    match_score = Column(Numeric)
    skill_match_pct = Column(Numeric)
    missing_skills = Column(JSONB)
    ranking_score = Column(Numeric)
    ranking_rationale = Column(Text)
    status = Column(Text, server_default=text("'received'"))
    expected_salary = Column(Numeric)
    approved_salary = Column(Numeric)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
