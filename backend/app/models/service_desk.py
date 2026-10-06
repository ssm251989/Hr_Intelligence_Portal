"""HR helpdesk, assets, separation / exit (docs/HRMS_COMPLETE_SPEC.txt Part 11). All
`TenantOwned` + RLS. Categories, priorities' SLA targets, business-hours calendars,
assignment strategy, notice periods, clearance checklists -- all tenant rows."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

TICKET_PRIORITIES = ("low", "medium", "high", "urgent")
TICKET_STATUSES = ("open", "in_progress", "waiting_on_requester", "resolved", "closed", "cancelled")
TICKET_CHANNELS = ("portal", "email", "in_app", "copilot")
ASSIGNMENT_STRATEGIES = ("round_robin", "skill", "queue")
ASSET_STATUSES = ("in_stock", "allocated", "in_repair", "retired", "lost")
ASSET_REQUEST_STATUSES = ("requested", "approved", "rejected", "fulfilled", "cancelled")
SEPARATION_TYPES = ("resignation", "termination", "absconding", "retirement", "contract_end", "death")
SEPARATION_STATUSES = ("submitted", "retention", "approved", "clearance", "completed", "withdrawn", "rejected")
CLEARANCE_DEPARTMENTS = ("it", "admin", "finance", "manager", "hr")
CLEARANCE_STATUSES = ("pending", "cleared", "waived")
CLEARANCE_KINDS = ("clearance", "asset_recovery", "access_revocation", "knowledge_transfer")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


# ---- business hours + SLA ----


class BusinessCalendar(Base, TenantOwned):
    """Working hours per location: `working_days` 0=Mon..6=Sun, local `start_time`/`end_time`
    ("09:00"/"18:00") in `timezone`, `holidays_json` ["YYYY-MM-DD", ...]."""

    __tablename__ = "business_calendars"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="business_calendars_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    timezone = Column(String(64), nullable=False)
    working_days = Column(JSONB, nullable=False, server_default=text("'[0, 1, 2, 3, 4]'::jsonb"))
    start_time = Column(String(5), nullable=False, server_default=text("'09:00'"))
    end_time = Column(String(5), nullable=False, server_default=text("'18:00'"))
    holidays_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class SlaPolicy(Base, TenantOwned):
    """Per category (NULL = default) and priority. When `use_requester_location_calendar`,
    the requester's location's calendar is used, falling back to `calendar_id`."""

    __tablename__ = "sla_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_code", "priority", name="sla_policies_category_priority_uq"),
        CheckConstraint(_in("priority", TICKET_PRIORITIES), name="sla_policies_priority_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    category_code = Column(String(100))
    priority = Column(String(10), nullable=False)
    response_minutes = Column(Integer, nullable=False)
    resolution_minutes = Column(Integer, nullable=False)
    calendar_id = Column(UUID(as_uuid=True), ForeignKey("business_calendars.id"))
    use_requester_location_calendar = Column(Boolean, nullable=False, server_default=text("true"))
    escalation_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # [{"at_pct": 80, "notify": "queue_lead"}, {"at_pct": 100, ...}]


class TicketQueue(Base, TenantOwned):
    __tablename__ = "ticket_queues"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="ticket_queues_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    lead_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    confidential = Column(Boolean, nullable=False, server_default=text("false"))  # POSH / grievance / whistle-blower


class TicketAssignmentRule(Base, TenantOwned):
    """`agents_json`: [{"user_id", "skills": [...]}]. round_robin rotates `cursor`; skill
    picks the least-loaded agent holding every skill in `required_skills_json`; queue
    leaves the ticket unassigned in `queue_code` for agents to pick."""

    __tablename__ = "ticket_assignment_rules"
    __table_args__ = (CheckConstraint(_in("strategy", ASSIGNMENT_STRATEGIES), name="ticket_assignment_rules_strategy_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_code = Column(String(100))  # NULL = fallback rule
    strategy = Column(String(20), nullable=False)
    queue_code = Column(String(100), nullable=False)
    agents_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    required_skills_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    cursor = Column(Integer, nullable=False, server_default=text("0"))
    priority = Column(Integer, nullable=False, server_default=text("100"))


class Ticket(Base, TenantOwned):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="tickets_tenant_number_uq"),
        CheckConstraint(_in("priority", TICKET_PRIORITIES), name="tickets_priority_check"),
        CheckConstraint(_in("status", TICKET_STATUSES), name="tickets_status_check"),
        CheckConstraint(_in("channel", TICKET_CHANNELS), name="tickets_channel_check"),
        CheckConstraint("csat_score IS NULL OR (csat_score BETWEEN 1 AND 5)", name="tickets_csat_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = Column(String(50), nullable=False)
    category_code = Column(String(100), nullable=False)  # `ticket_category` master
    subcategory_code = Column(String(100))
    priority = Column(String(10), nullable=False, server_default=text("'medium'"))
    subject = Column(Text, nullable=False)
    description = Column(Text)
    channel = Column(String(20), nullable=False, server_default=text("'portal'"))
    requester_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    requester_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    requester_email = Column(Text)
    queue_code = Column(String(100))
    assignee_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    status = Column(String(30), nullable=False, server_default=text("'open'"))
    confidential = Column(Boolean, nullable=False, server_default=text("false"))
    sla_policy_id = Column(UUID(as_uuid=True), ForeignKey("sla_policies.id"))
    calendar_id = Column(UUID(as_uuid=True), ForeignKey("business_calendars.id"))
    response_due_at = Column(DateTime(timezone=True))
    resolution_due_at = Column(DateTime(timezone=True))
    first_responded_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    paused_at = Column(DateTime(timezone=True))  # waiting_on_requester stops the resolution clock
    escalation_level = Column(Integer, nullable=False, server_default=text("0"))
    csat_score = Column(Integer)
    csat_comment = Column(Text)
    inbound_message_id = Column(UUID(as_uuid=True), ForeignKey("inbound_messages.id"))
    ai_suggestion_json = Column(JSONB)  # Part 12 triage agent's suggestion -- advisory
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class TicketComment(Base, TenantOwned):
    __tablename__ = "ticket_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    author = Column(Text, nullable=False)
    author_is_agent = Column(Boolean, nullable=False, server_default=text("false"))
    body = Column(Text, nullable=False)
    internal = Column(Boolean, nullable=False, server_default=text("false"))  # agent-only note
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class KbArticle(Base, TenantOwned):
    __tablename__ = "kb_articles"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="kb_articles_tenant_slug_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(200), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    category_code = Column(String(100))
    tags_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    helpful_count = Column(Integer, nullable=False, server_default=text("0"))
    deflection_count = Column(Integer, nullable=False, server_default=text("0"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- assets ----


class Asset(Base, TenantOwned):
    """`depreciation_json` (optional): {"method": "straight_line", "life_months": 36, "salvage_value": 0}."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_tag", name="assets_tenant_tag_uq"),
        CheckConstraint(_in("status", ASSET_STATUSES), name="assets_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_tag = Column(String(100), nullable=False)
    category_code = Column(String(100), nullable=False)  # `asset_category` master
    name = Column(Text, nullable=False)
    serial_number = Column(Text)
    purchase_date = Column(Date)
    purchase_cost = Column(Numeric)
    currency = Column(String(3))
    warranty_until = Column(Date)
    vendor = Column(Text)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    status = Column(String(20), nullable=False, server_default=text("'in_stock'"))
    depreciation_json = Column(JSONB)
    custom_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AssetAllocation(Base, TenantOwned):
    __tablename__ = "asset_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    allocated_by = Column(Text)
    allocated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledgement_text = Column(Text)
    returned_at = Column(DateTime(timezone=True))
    return_condition = Column(String(30))  # good | damaged | lost
    return_notes = Column(Text)
    received_by = Column(Text)


class AssetMaintenance(Base, TenantOwned):
    __tablename__ = "asset_maintenance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    performed_on = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    cost = Column(Numeric)
    vendor = Column(Text)
    created_by = Column(Text)


class AssetRequest(Base, TenantOwned):
    __tablename__ = "asset_requests"
    __table_args__ = (CheckConstraint(_in("status", ASSET_REQUEST_STATUSES), name="asset_requests_status_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    category_code = Column(String(100), nullable=False)
    reason = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'requested'"))
    workflow_instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id"))
    fulfilled_allocation_id = Column(UUID(as_uuid=True), ForeignKey("asset_allocations.id"))
    source = Column(String(30), nullable=False, server_default=text("'employee'"))  # employee | onboarding | copilot
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- separation / offboarding ----


class Separation(Base, TenantOwned):
    __tablename__ = "separations"
    __table_args__ = (
        CheckConstraint(_in("separation_type", SEPARATION_TYPES), name="separations_type_check"),
        CheckConstraint(_in("status", SEPARATION_STATUSES), name="separations_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    separation_type = Column(String(20), nullable=False)
    initiated_by = Column(Text, nullable=False)
    reason_code = Column(String(100))  # `exit_reason` master
    reason_text = Column(Text)
    voluntary = Column(Boolean, nullable=False, server_default=text("true"))
    regretted = Column(Boolean)
    submitted_on = Column(Date, nullable=False)
    notice_period_days = Column(Integer, nullable=False)
    requested_lwd = Column(Date)
    approved_lwd = Column(Date)
    notice_waived_days = Column(Integer, nullable=False, server_default=text("0"))
    notice_buyout_days = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(20), nullable=False, server_default=text("'submitted'"))
    retention_notes = Column(Text)
    workflow_instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id"))
    exit_interview_json = Column(JSONB)
    exit_interview_ai_summary_json = Column(JSONB)  # advisory, HITL
    exit_interview_hr_notes = Column(Text)  # fix 2026-10-06: HR's private notes, never shown to the employee or managers
    rehire_eligible = Column(Boolean)
    alumni_opt_in = Column(Boolean, nullable=False, server_default=text("false"))
    absconding_notices_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    relieving_letter_id = Column(UUID(as_uuid=True), ForeignKey("letter_records.id"))
    experience_letter_id = Column(UUID(as_uuid=True), ForeignKey("letter_records.id"))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ClearanceItem(Base, TenantOwned):
    __tablename__ = "clearance_items"
    __table_args__ = (
        CheckConstraint(_in("department", CLEARANCE_DEPARTMENTS), name="clearance_items_department_check"),
        CheckConstraint(_in("status", CLEARANCE_STATUSES), name="clearance_items_status_check"),
        CheckConstraint(_in("kind", CLEARANCE_KINDS), name="clearance_items_kind_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    separation_id = Column(UUID(as_uuid=True), ForeignKey("separations.id"), nullable=False)
    department = Column(String(20), nullable=False)
    kind = Column(String(30), nullable=False, server_default=text("'clearance'"))
    title = Column(Text, nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    asset_allocation_id = Column(UUID(as_uuid=True), ForeignKey("asset_allocations.id"))
    blocks_relieving = Column(Boolean, nullable=False, server_default=text("true"))
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    amount_due = Column(Numeric)
    notes = Column(Text)
    cleared_by = Column(Text)
    cleared_at = Column(DateTime(timezone=True))
