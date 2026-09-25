"""Performance, goals/OKR, 360, calibration, compensation planning, talent & succession
(docs/HRMS_COMPLETE_SPEC.txt Part 10). All `TenantOwned` + RLS.

Everything a client would configure differently -- cycle stages/sections/weights, rating
scales, anonymity thresholds, distribution guidelines, merit matrices, salary bands,
budgets -- is a row here, never a code constant.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

GOAL_LEVELS = ("company", "department", "team", "individual")
GOAL_STATUSES = ("draft", "active", "completed", "cancelled")
FEEDBACK_KINDS = ("feedback", "praise")
FEEDBACK_VISIBILITY = ("private", "manager", "public")
CYCLE_TYPES = ("annual", "half_yearly", "quarterly", "probation", "project_end")
CYCLE_STATUSES = ("draft", "active", "calibration", "closed")
REVIEW_STAGES = ("self", "manager", "peer", "skip_level", "reviewer")
REVIEW_STATUSES = ("pending", "draft", "submitted")
NOMINATION_STATUSES = ("proposed", "approved", "rejected")
CALIBRATION_ENFORCEMENT = ("soft", "hard")
CALIBRATION_STATUSES = ("open", "finalized")
PROPOSAL_STATUSES = ("draft", "submitted", "approved", "rejected", "applied")
READINESS_LEVELS = ("ready_now", "ready_1_2_years", "ready_3_plus_years")
FLIGHT_RISK_LEVELS = ("low", "medium", "high")
OPPORTUNITY_TYPES = ("gig", "project", "ijp")
OPPORTUNITY_STATUSES = ("open", "closed", "filled")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


# ---- A. goals & OKRs ----


class GoalLibraryItem(Base, TenantOwned):
    __tablename__ = "goal_library"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="goal_library_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    kpi_json = Column(JSONB)
    job_family = Column(String(100))


class Goal(Base, TenantOwned):
    """`kpi_json`: {"metric", "unit", "baseline", "target", "direction": "increase"|"decrease"}.
    `parent_goal_id` is the cascade (company -> department -> team -> individual)."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(_in("level", GOAL_LEVELS), name="goals_level_check"),
        CheckConstraint(_in("status", GOAL_STATUSES), name="goals_status_check"),
        CheckConstraint("weightage >= 0 AND weightage <= 100", name="goals_weightage_check"),
        CheckConstraint("progress_pct >= 0 AND progress_pct <= 100", name="goals_progress_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    description = Column(Text)
    level = Column(String(20), nullable=False, server_default=text("'individual'"))
    parent_goal_id = Column(UUID(as_uuid=True), ForeignKey("goals.id"))
    owner_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))  # NULL for company goals
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("review_cycles.id"))
    library_code = Column(String(100))
    weightage = Column(Numeric, nullable=False, server_default=text("0"))
    kpi_json = Column(JSONB)
    progress_pct = Column(Numeric, nullable=False, server_default=text("0"))
    confidence = Column(Integer)  # 1-5
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    external_ref = Column(Text)  # e.g. a Jira epic key an integration webhook reports progress against
    due_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class GoalCheckin(Base, TenantOwned):
    __tablename__ = "goal_checkins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("goals.id"), nullable=False)
    progress_pct = Column(Numeric, nullable=False)
    current_value = Column(Numeric)
    confidence = Column(Integer)
    comment = Column(Text)
    source = Column(String(30), nullable=False, server_default=text("'manual'"))  # manual | integration
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- B. continuous performance ----


class OneOnOne(Base, TenantOwned):
    __tablename__ = "one_on_ones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manager_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    scheduled_for = Column(DateTime(timezone=True))
    agenda_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    shared_notes = Column(Text)
    manager_private_notes = Column(Text)  # never shown to the employee
    action_items_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class Feedback(Base, TenantOwned):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(_in("kind", FEEDBACK_KINDS), name="feedback_kind_check"),
        CheckConstraint(_in("visibility", FEEDBACK_VISIBILITY), name="feedback_visibility_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    to_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    kind = Column(String(20), nullable=False, server_default=text("'feedback'"))
    visibility = Column(String(20), nullable=False, server_default=text("'private'"))
    text_body = Column(Text, nullable=False)
    value_code = Column(String(100))  # a company value this praise is tagged with
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- C. review cycles ----


class RatingScale(Base, TenantOwned):
    """`points_json`: [{"value": 1, "label": "Needs improvement"}, ...] ascending."""

    __tablename__ = "rating_scales"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="rating_scales_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    points_json = Column(JSONB, nullable=False)


class ReviewCycle(Base, TenantOwned):
    """Everything per-cycle (spec: "all configurable per cycle"):
    - `eligibility_jsonlogic` over the employee context (see performance/reviews.py)
    - `stages_json`: [{"stage": REVIEW_STAGES, "weight": 70, "due_date": "YYYY-MM-DD"}]
    - `sections_json`: [{"key": "goals"|"competencies"|"values"|"questions", "weight": 60, "items": [...]}]
    - `anonymity_json`: {"peer_anonymous": true, "min_peer_responses": 3, "peer_visible_to_employee": true}
    - `reminder_days_before`: comms reminders before each stage deadline."""

    __tablename__ = "review_cycles"
    __table_args__ = (
        CheckConstraint(_in("cycle_type", CYCLE_TYPES), name="review_cycles_type_check"),
        CheckConstraint(_in("status", CYCLE_STATUSES), name="review_cycles_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    cycle_type = Column(String(20), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    eligibility_jsonlogic = Column(JSONB)
    stages_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    sections_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    rating_scale_id = Column(UUID(as_uuid=True), ForeignKey("rating_scales.id"))
    anonymity_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    reminder_days_before = Column(JSONB, nullable=False, server_default=text("'[3, 1]'::jsonb"))
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ReviewNomination(Base, TenantOwned):
    __tablename__ = "review_nominations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cycle_id", "employee_id", "nominee_employee_id", name="review_nominations_uq"),
        CheckConstraint(_in("status", NOMINATION_STATUSES), name="review_nominations_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("review_cycles.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    nominee_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'proposed'"))
    decided_by = Column(Text)


class Review(Base, TenantOwned):
    """One reviewer's input for one employee in one stage. `section_scores_json`:
    {section_key: score}; `goal_ratings_json`: {goal_id: rating}."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cycle_id", "employee_id", "reviewer_employee_id", "stage", name="reviews_uq"),
        CheckConstraint(_in("stage", REVIEW_STAGES), name="reviews_stage_check"),
        CheckConstraint(_in("status", REVIEW_STATUSES), name="reviews_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("review_cycles.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    reviewer_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    stage = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    section_scores_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    goal_ratings_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    answers_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    comments = Column(Text)
    overall_rating = Column(Numeric)
    ai_draft_json = Column(JSONB)  # {"summary", "bias_flags", "prompt_version"} -- never auto-submitted
    submitted_at = Column(DateTime(timezone=True))


# ---- D. calibration ----


class CalibrationSession(Base, TenantOwned):
    """`distribution_json`: {"<rating value>": target_pct, ...}; `tolerance_pct` is how far
    a bucket may drift before soft = warn / hard = block finalize."""

    __tablename__ = "calibration_sessions"
    __table_args__ = (
        CheckConstraint(_in("enforcement", CALIBRATION_ENFORCEMENT), name="calibration_sessions_enforcement_check"),
        CheckConstraint(_in("status", CALIBRATION_STATUSES), name="calibration_sessions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("review_cycles.id"), nullable=False)
    name = Column(Text, nullable=False)
    distribution_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    tolerance_pct = Column(Numeric, nullable=False, server_default=text("5"))
    enforcement = Column(String(10), nullable=False, server_default=text("'soft'"))
    status = Column(String(20), nullable=False, server_default=text("'open'"))
    finalized_by = Column(Text)
    finalized_at = Column(DateTime(timezone=True))


class CalibrationEntry(Base, TenantOwned):
    __tablename__ = "calibration_entries"
    __table_args__ = (UniqueConstraint("tenant_id", "session_id", "employee_id", name="calibration_entries_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("calibration_sessions.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    original_rating = Column(Numeric)
    performance_rating = Column(Numeric)
    potential_rating = Column(Integer)  # 1 low / 2 medium / 3 high -- the 9-box y axis


class CalibrationAudit(Base, TenantOwned):
    """Every drag-to-adjust move -- the calibration audit the spec's TESTS name."""

    __tablename__ = "calibration_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id = Column(UUID(as_uuid=True), ForeignKey("calibration_entries.id"), nullable=False)
    field = Column(String(30), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    reason = Column(Text, nullable=False)
    actor = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- E. compensation planning ----


class SalaryBand(Base, TenantOwned):
    __tablename__ = "salary_bands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "grade", "location_id", "currency", name="salary_bands_uq"),
        CheckConstraint("min_amount <= mid_amount AND mid_amount <= max_amount", name="salary_bands_order_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grade = Column(String(50), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    currency = Column(String(3), nullable=False)
    min_amount = Column(Numeric, nullable=False)
    mid_amount = Column(Numeric, nullable=False)
    max_amount = Column(Numeric, nullable=False)


class MeritMatrix(Base, TenantOwned):
    """`cells_json`: [{"rating_min", "rating_max", "compa_min", "compa_max", "pct_min", "pct_max"}]
    -- rating x compa-ratio -> merit increase % range. Bounds are [min, max)."""

    __tablename__ = "merit_matrices"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="merit_matrices_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    cells_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    bonus_rules_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {"<rating>": target bonus % of base}


class CompensationCycle(Base, TenantOwned):
    __tablename__ = "compensation_cycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    review_cycle_id = Column(UUID(as_uuid=True), ForeignKey("review_cycles.id"))
    merit_matrix_id = Column(UUID(as_uuid=True), ForeignKey("merit_matrices.id"))
    effective_date = Column(Date, nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'draft'"))


class CompensationBudget(Base, TenantOwned):
    __tablename__ = "compensation_budgets"
    __table_args__ = (UniqueConstraint("tenant_id", "comp_cycle_id", "department_id", name="compensation_budgets_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comp_cycle_id = Column(UUID(as_uuid=True), ForeignKey("compensation_cycles.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    merit_pool = Column(Numeric, nullable=False, server_default=text("0"))
    bonus_pool = Column(Numeric, nullable=False, server_default=text("0"))


class CompensationProposal(Base, TenantOwned):
    """A manager-worksheet row. Approved proposals become an effective-dated
    `compensation_records` row (+ optional letter)."""

    __tablename__ = "compensation_proposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "comp_cycle_id", "employee_id", name="compensation_proposals_uq"),
        CheckConstraint(_in("status", PROPOSAL_STATUSES), name="compensation_proposals_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comp_cycle_id = Column(UUID(as_uuid=True), ForeignKey("compensation_cycles.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    current_base = Column(Numeric, nullable=False)
    rating = Column(Numeric)
    compa_ratio = Column(Numeric)
    guideline_min_pct = Column(Numeric)
    guideline_max_pct = Column(Numeric)
    merit_pct = Column(Numeric, nullable=False, server_default=text("0"))
    bonus_amount = Column(Numeric, nullable=False, server_default=text("0"))
    promotion_to_grade = Column(String(50))
    justification = Column(Text)  # required when outside guideline
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    workflow_instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id"))
    decided_by = Column(Text)


class CompensationRecord(Base, TenantOwned):
    """Effective-dated compensation history (same new-row-per-change discipline as Part 7's
    employment_records)."""

    __tablename__ = "compensation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    base_amount = Column(Numeric, nullable=False)
    currency = Column(String(3), nullable=False)
    components_json = Column(JSONB)
    reason = Column(Text)
    proposal_id = Column(UUID(as_uuid=True), ForeignKey("compensation_proposals.id"))
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- F. talent & succession ----


class TalentProfile(Base, TenantOwned):
    __tablename__ = "talent_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", name="talent_profiles_employee_uq"),
        CheckConstraint("flight_risk_manager IS NULL OR " + _in("flight_risk_manager", FLIGHT_RISK_LEVELS), name="talent_profiles_flight_risk_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    aspirations = Column(Text)
    mobility_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {"relocate": bool, "locations": [...]}
    career_path_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    flight_risk_ai = Column(Numeric)  # 0-1 estimate -- advisory, clearly labelled
    flight_risk_ai_factors_json = Column(JSONB)
    flight_risk_manager = Column(String(10))  # the human judgment that actually counts (HITL)
    flight_risk_notes = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class SuccessionSlate(Base, TenantOwned):
    __tablename__ = "succession_slates"
    __table_args__ = (UniqueConstraint("tenant_id", "position_id", name="succession_slates_position_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class SuccessionCandidate(Base, TenantOwned):
    __tablename__ = "succession_candidates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slate_id", "employee_id", name="succession_candidates_uq"),
        CheckConstraint(_in("readiness", READINESS_LEVELS), name="succession_candidates_readiness_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slate_id = Column(UUID(as_uuid=True), ForeignKey("succession_slates.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    readiness = Column(String(30), nullable=False)
    rank = Column(Integer, nullable=False, server_default=text("1"))
    development_actions_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    assessed_by = Column(Text)
    assessed_at = Column(DateTime(timezone=True), server_default=text("now()"))


class InternalOpportunity(Base, TenantOwned):
    __tablename__ = "internal_opportunities"
    __table_args__ = (
        CheckConstraint(_in("type", OPPORTUNITY_TYPES), name="internal_opportunities_type_check"),
        CheckConstraint(_in("status", OPPORTUNITY_STATUSES), name="internal_opportunities_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String(20), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    skills_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"))
    posted_by = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'open'"))
    closes_on = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class InternalApplication(Base, TenantOwned):
    __tablename__ = "internal_applications"
    __table_args__ = (UniqueConstraint("tenant_id", "opportunity_id", "employee_id", name="internal_applications_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("internal_opportunities.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    note = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'applied'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    manager_notified = Column(Boolean, nullable=False, server_default=text("false"))
