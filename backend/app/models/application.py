from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Numeric, String, Text, text
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
    # fix 2026-10-05: how an offer / a new joiner ended (app/onboarding/joiner_actions.py)
    "offer_withdrawn", "offer_declined", "no_show", "left_after_joining",
)

# No further transition endpoint exists in the codebase for any of these -- confirmed by
# grepping every screening/shortlisting/scheduling/salary/bgv/offers router for each string
# as a precondition. "Terminal" by omission (no code path leaves them), not by a flag on
# the row. Used to define "active candidate" (has >=1 application not in this set) and by
# the next-actions lookup (see app/candidates/pipeline_actions.py).
TERMINAL_APPLICATION_STATUSES = (
    "hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected", "onboarding_completed",
    "offer_withdrawn", "offer_declined", "no_show", "left_after_joining",
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
    # Part 17.4/17.5: composite_score IS the one "Match score (0-100)" (configurable, weighted);
    # match_score is kept as the AI fit, now just one factor of it. The breakdown behind the
    # latest score ("Why this score"), the knock-out result, when and with which rules.
    score_breakdown = Column(JSONB)
    knocked_out = Column(Boolean, nullable=False, server_default=text("false"))
    scored_at = Column(DateTime(timezone=True))
    # Part 17.8: latest salary check against the band (app/recruitment/salary_auto.py)
    salary_check = Column(JSONB)
    scoring_rule_set_id = Column(UUID(as_uuid=True), ForeignKey("scoring_rule_sets.id", ondelete="SET NULL"))
    ranking_score = Column(Numeric)
    ranking_rationale = Column(Text)
    status = Column(Text, server_default=text("'received'"))
    removed_at = Column(DateTime(timezone=True))  # Part 17.15: its candidate is in the Recycle bin
    removed_reason = Column(String(30))  # Part 21: None = its candidate was removed; "job_cleanup" = its closed job went to the bin; "exit" = hiring data moved on exit
    # Set only while status == 'on_hold' -- the status to restore on resume (see
    # app/candidates/hold.py). Cleared back to null on resume; never meaningful otherwise.
    previous_status = Column(Text)
    hold_reason = Column(Text)  # Part 18.8: "job_closed" when the job's closing put it on hold (reopen restores it)
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
