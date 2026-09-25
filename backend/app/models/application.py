from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

APPLICATION_STATUSES = (
    "received", "screened", "hr_selected", "hr_rejected",
    "interview_scheduled", "interview_selected", "interview_rejected",
    "salary_ok", "salary_above_band", "salary_approved", "salary_rejected",
    "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected",
    "offer_sent", "onboarding_started", "onboarding_completed",
    "on_hold",
)

# No further transition endpoint exists in the codebase for any of these -- confirmed by
# grepping every screening/shortlisting/scheduling/salary/bgv/offers router for each string
# as a precondition. "Terminal" by omission (no code path leaves them), not by a flag on
# the row. Used to define "active candidate" (has >=1 application not in this set) and by
# the next-actions lookup (see app/candidates/pipeline_actions.py).
TERMINAL_APPLICATION_STATUSES = (
    "hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected", "onboarding_completed",
)


class Application(Base, TenantOwned):
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
    # Equal-weighted average of skills/experience/location/certificates/match_score (see
    # app/screening/service.py) -- the other four sub-scores are deliberately NOT their own
    # columns here, only this final number is. The full breakdown lives in the audit_log
    # entry logged alongside it (action="ai_screening_scored"), which is what the
    # Candidates List's Remarks column reads from rather than a separately maintained field.
    composite_score = Column(Numeric)
    ranking_score = Column(Numeric)
    ranking_rationale = Column(Text)
    status = Column(Text, server_default=text("'received'"))
    # Set only while status == 'on_hold' -- the status to restore on resume (see
    # app/candidates/hold.py). Cleared back to null on resume; never meaningful otherwise.
    previous_status = Column(Text)
    expected_salary = Column(Numeric)
    approved_salary = Column(Numeric)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Part 6 section 1 -- see candidates.py's own custom_fields column comment.
    custom_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Part 8 section 3 -- DPDP consent capture at career-site apply time. Both null for any
    # application not created through the public apply flow (e.g. local import).
    consent_given_at = Column(DateTime(timezone=True))
    consent_version = Column(Text)
