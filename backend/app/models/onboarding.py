"""Pre-boarding & onboarding tables (docs/HRMS_COMPLETE_SPEC.txt Part 9) -- the pre-boarding
case (offer accepted -> joining day) with its magic-link portal, document collection,
background verification cases, workflow-style onboarding plans generated from templates,
and the JSONLogic `assignment_rules` table conversion uses to pick plans/letters/roles.
All `TenantOwned` + RLS, same as every other business-data table in this build.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

PREBOARDING_STATUSES = ("invited", "in_progress", "ready", "joined", "no_show", "revoked")
PREBOARDING_DOC_STATUSES = ("pending", "verified", "rejected")
BGV_SUBJECT_TYPES = ("candidate", "employee")
BGV_CHECK_TYPES = ("identity", "address", "education", "employment", "criminal", "credit", "drug")
BGV_CASE_STATUSES = ("awaiting_consent", "initiated", "in_progress", "completed", "cancelled")
BGV_CHECK_STATUSES = ("pending", "in_progress", "clear", "discrepancy", "unable_to_verify")
BGV_DECISIONS = ("pending", "clear", "accept_with_discrepancy", "reject")
ONBOARDING_OWNER_ROLES = ("hr", "it", "admin", "manager", "buddy", "finance", "new_hire")
ONBOARDING_TASK_STATUSES = ("pending", "blocked", "done", "skipped")
ASSIGNMENT_TARGET_TYPES = ("onboarding_plan_template", "letter_template", "role")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


class PreboardingCase(Base, TenantOwned):
    """One per accepted offer. `portal_token` is the magic-link credential for the
    PreboardingPortal (app/onboarding/portal.py) -- long-lived (joining can be weeks away),
    rotatable, and never an app login."""

    __tablename__ = "preboarding_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "portal_token", name="preboarding_cases_tenant_token_uq"),
        CheckConstraint(_in("status", PREBOARDING_STATUSES), name="preboarding_cases_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    offer_id = Column(UUID(as_uuid=True), ForeignKey("offers.id"))
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))  # the pre_hire employee row, set at case creation
    email = Column(Text, nullable=False)
    joining_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'invited'"))
    portal_token = Column(Text, nullable=False)
    portal_token_expires_at = Column(DateTime(timezone=True), nullable=False)
    attributes_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # entity/location/worker_type/grade -- what forms + assignment rules key on
    form_submissions_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {form_code: {data, submitted_at}}
    policy_acks_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {policy_code: acknowledged_at}
    welcome_content_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # videos/policies/team intro/buddy/agenda
    history_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # joining-date changes, no-show, revoke
    joined_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class PreboardingDocument(Base, TenantOwned):
    __tablename__ = "preboarding_documents"
    __table_args__ = (
        CheckConstraint(_in("verification_status", PREBOARDING_DOC_STATUSES), name="preboarding_documents_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("preboarding_cases.id"), nullable=False)
    document_type_code = Column(String(100), nullable=False)  # a `document_type` master value code
    file_path = Column(Text)
    extracted_json = Column(JSONB)  # AI prefill -- advisory, HR verifies
    verification_status = Column(String(20), nullable=False, server_default=text("'pending'"))
    verified_by = Column(Text)
    verified_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)
    uploaded_at = Column(DateTime(timezone=True), server_default=text("now()"))


class BgvCase(Base, TenantOwned):
    """`checks_json`: [{"type": <BGV_CHECK_TYPES>, "status": <BGV_CHECK_STATUSES>, "notes": ..}].
    The final `decision` is always a human's (HITL) -- a vendor webhook only ever updates
    per-check statuses/report, never the decision."""

    __tablename__ = "bgv_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "webhook_token", name="bgv_cases_tenant_webhook_token_uq"),
        CheckConstraint(_in("subject_type", BGV_SUBJECT_TYPES), name="bgv_cases_subject_type_check"),
        CheckConstraint(_in("status", BGV_CASE_STATUSES), name="bgv_cases_status_check"),
        CheckConstraint(_in("decision", BGV_DECISIONS), name="bgv_cases_decision_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_type = Column(String(20), nullable=False)
    subject_id = Column(UUID(as_uuid=True), nullable=False)
    preboarding_case_id = Column(UUID(as_uuid=True), ForeignKey("preboarding_cases.id"))
    package_code = Column(String(100))
    checks_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    vendor_connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"))
    vendor_reference = Column(Text)
    webhook_token = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, server_default=text("'awaiting_consent'"))
    consent_at = Column(DateTime(timezone=True))
    consent_text = Column(Text)
    report_file_path = Column(Text)
    discrepancy = Column(Text)
    decision = Column(String(30), nullable=False, server_default=text("'pending'"))
    decided_by = Column(Text)
    decided_at = Column(DateTime(timezone=True))
    initiated_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class OnboardingPlanTemplate(Base, TenantOwned):
    """`tasks_json`: [{"key", "title", "owner_role" (ONBOARDING_OWNER_ROLES),
    "due_offset_days" (relative to DOJ: -7 / 0 / 30), "depends_on": [key..],
    "form_code"?, "requires_approval"?, "kind"?: "task"|"checkin"|"provisioning"}]."""

    __tablename__ = "onboarding_plan_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="onboarding_plan_templates_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    tasks_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class OnboardingPlan(Base, TenantOwned):
    __tablename__ = "onboarding_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "case_id", name="onboarding_plans_tenant_case_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("preboarding_cases.id"), nullable=False)
    template_id = Column(UUID(as_uuid=True), ForeignKey("onboarding_plan_templates.id"), nullable=False)
    template_code = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class OnboardingTask(Base, TenantOwned):
    __tablename__ = "onboarding_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "plan_id", "key", name="onboarding_tasks_tenant_plan_key_uq"),
        CheckConstraint(_in("owner_role", ONBOARDING_OWNER_ROLES), name="onboarding_tasks_owner_role_check"),
        CheckConstraint(_in("status", ONBOARDING_TASK_STATUSES), name="onboarding_tasks_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("onboarding_plans.id"), nullable=False)
    key = Column(String(100), nullable=False)
    title = Column(Text, nullable=False)
    kind = Column(String(20), nullable=False, server_default=text("'task'"))
    owner_role = Column(String(20), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    due_offset_days = Column(Integer, nullable=False, server_default=text("0"))
    due_date = Column(Date, nullable=False)
    depends_on_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    form_code = Column(String(100))
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    completed_by = Column(Text)
    completed_at = Column(DateTime(timezone=True))
    response_json = Column(JSONB)  # a 30/60/90 check-in's own answers


class AssignmentRule(Base, TenantOwned):
    """Policy assignment by rules (section 4): when `condition_jsonlogic` matches the
    conversion context (entity/location/grade/worker_type/department), `target_ref` is
    assigned. Lowest `priority` wins per target_type for single-valued targets
    (onboarding_plan_template, letter_template); `role` targets are additive."""

    __tablename__ = "assignment_rules"
    __table_args__ = (CheckConstraint(_in("target_type", ASSIGNMENT_TARGET_TYPES), name="assignment_rules_target_type_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    target_type = Column(String(40), nullable=False)
    target_ref = Column(Text, nullable=False)  # template code / role name
    condition_jsonlogic = Column(JSONB)  # NULL = always matches
    priority = Column(Integer, nullable=False, server_default=text("100"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
