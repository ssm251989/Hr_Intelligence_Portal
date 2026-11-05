"""Analytics, report builder, HR Copilot, AI agents and AI governance (docs/
HRMS_COMPLETE_SPEC.txt Part 12). All `TenantOwned` + RLS.

`knowledge_chunks.embedding_json` holds a vector as a JSON float array: this installation's
Postgres has no pgvector extension available, so retrieval is lexical by default and
cosine-over-JSON when embeddings exist (see app/copilot/retrieval.py). Switching the
column to `vector(n)` + an ivfflat index is a contained migration once pgvector is
installed -- nothing outside retrieval.py reads the column.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

REPORT_FORMATS = ("csv", "xlsx")
SCHEDULE_FREQUENCIES = ("daily", "weekly", "monthly")
DRAFT_ACTIONS = ("raise_ticket", "request_asset", "request_letter", "hr_handover")  # Part 22.1: + hand over to HR (Helpdesk off)
DRAFT_STATUSES = ("draft", "confirmed", "discarded", "failed")
AGENTS = ("recruiter", "onboarding", "helpdesk_triage", "policy_checker")
SUGGESTION_STATUSES = ("pending", "approved", "edited", "rejected")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


# ---- analytics / report builder ----


class SavedReport(Base, TenantOwned):
    """`definition_json`: {"columns": [...], "filters": [{"field","op","value"}], "group_by": [...],
    "measures": [{"field","agg","as"}], "pivot": {"on", "value"}?, "sort": [{"field","dir"}],
    "limit": n, "as_of": "YYYY-MM-DD"?, "chart": {"type", "x", "y"}?}"""

    __tablename__ = "saved_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    dataset_code = Column(String(100), nullable=False)
    definition_json = Column(JSONB, nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    shared_role_names = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ReportSchedule(Base, TenantOwned):
    """Runs AS the report owner (their scope, their field security), delivered through a
    comms template to `recipients_json` (emails). `next_run_at` is computed in the tenant's
    timezone from frequency/day/hour."""

    __tablename__ = "report_schedules"
    __table_args__ = (
        CheckConstraint(_in("frequency", SCHEDULE_FREQUENCIES), name="report_schedules_frequency_check"),
        CheckConstraint(_in("format", REPORT_FORMATS), name="report_schedules_format_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("saved_reports.id"), nullable=False)
    frequency = Column(String(10), nullable=False)
    day_of_week = Column(Integer)  # 0=Mon, for weekly
    day_of_month = Column(Integer)  # 1-28, for monthly
    hour = Column(Integer, nullable=False, server_default=text("8"))
    format = Column(String(10), nullable=False, server_default=text("'csv'"))
    recipients_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    template_key = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    next_run_at = Column(DateTime(timezone=True))
    last_run_at = Column(DateTime(timezone=True))


class ReportDelivery(Base, TenantOwned):
    __tablename__ = "report_deliveries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("report_schedules.id"), nullable=False)
    run_at = Column(DateTime(timezone=True), server_default=text("now()"))
    status = Column(String(20), nullable=False)  # sent | failed | empty
    row_count = Column(Integer)
    file_ref = Column(Text)
    error = Column(Text)


class Dashboard(Base, TenantOwned):
    """Role dashboards with configurable widgets: `widgets_json` [{"type": "metric"|"report",
    "metric": <metric code> | "report_id": .., "title", "size": "sm"|"md"|"lg"}]."""

    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="dashboards_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    audience_role = Column(String(100))  # CHRO / HRBP / Recruiter / Manager / Employee (a role name)
    widgets_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


# ---- HR Copilot ----


class KnowledgeDocument(Base, TenantOwned):
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    source = Column(String(30), nullable=False, server_default=text("'upload'"))  # upload | kb_article
    source_ref = Column(Text)
    language = Column(String(10), nullable=False, server_default=text("'en'"))
    audience_role_names = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # [] = everyone
    # processing -> active ("Ready for HR assistant") | failed (+ error); retired = replaced by a
    # newer version (kept for answers that cited it); deleted = removed by HR (chunks + file gone)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    uploaded_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Fix 2026-10-05: Settings > Company > Policies & handbook (app/copilot/policies.py)
    category = Column(String(30))  # leave | conduct | benefits | it | other
    version = Column(String(30))
    effective_date = Column(Date)
    file_path = Column(Text)  # "storage:<key>" in the storage connection, else uploads/policies/<tenant>/...
    file_name = Column(Text)
    content_type = Column(String(120))
    size_bytes = Column(Integer)
    error = Column(Text)
    processed_at = Column(DateTime(timezone=True))
    replaces_id = Column(UUID(as_uuid=True))  # the older version this one replaces once Ready
    updated_at = Column(DateTime(timezone=True))


class KnowledgeChunk(Base, TenantOwned):
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_documents.id"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    heading = Column(Text)
    body = Column(Text, nullable=False)
    embedding_json = Column(JSONB)


class CopilotConversation(Base, TenantOwned):
    __tablename__ = "copilot_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    language = Column(String(10), nullable=False, server_default=text("'en'"))
    channel = Column(String(20), nullable=False, server_default=text("'web'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class CopilotMessage(Base, TenantOwned):
    __tablename__ = "copilot_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("copilot_conversations.id"), nullable=False)
    role = Column(String(10), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    citations_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    tool_calls_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    confidence = Column(Numeric)
    handover_ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"))
    decision_log_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class CopilotDraft(Base, TenantOwned):
    """An action proposed in chat -- never executed until the user confirms it."""

    __tablename__ = "copilot_drafts"
    __table_args__ = (
        CheckConstraint(_in("action", DRAFT_ACTIONS), name="copilot_drafts_action_check"),
        CheckConstraint(_in("status", DRAFT_STATUSES), name="copilot_drafts_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("copilot_conversations.id"))
    action = Column(String(30), nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    result_ref = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- AI agents (HITL) ----


class AgentSuggestion(Base, TenantOwned):
    """Lands in the reviewer's inbox; nothing happens until approve/edit/reject."""

    __tablename__ = "agent_suggestions"
    __table_args__ = (
        CheckConstraint(_in("agent", AGENTS), name="agent_suggestions_agent_check"),
        CheckConstraint(_in("status", SUGGESTION_STATUSES), name="agent_suggestions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent = Column(String(30), nullable=False)
    kind = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    payload_json = Column(JSONB, nullable=False)
    reviewer_permission = Column(String(120), nullable=False)  # who may act on it
    reviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # optional direct assignee
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    final_payload_json = Column(JSONB)
    reviewed_by = Column(Text)
    reviewed_at = Column(DateTime(timezone=True))
    decision_log_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- AI governance ----


class AiDecisionLog(Base, TenantOwned):
    """Every governed AI call: input refs (ids, never raw PII), model, prompt version,
    output, human reviewer, final decision -- for audit and bias review."""

    __tablename__ = "ai_decision_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature = Column(String(100), nullable=False)
    purpose = Column(String(100), nullable=False)
    model = Column(String(100))
    prompt_key = Column(String(100))
    prompt_version = Column(Integer)
    input_refs_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    redactions_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # counts per redacted field type
    output_json = Column(JSONB)
    status = Column(String(20), nullable=False, server_default=text("'ok'"))  # ok | error | blocked
    error = Column(Text)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    human_reviewer = Column(Text)
    final_decision = Column(String(30))  # accepted | edited | rejected | n/a
    decided_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AiUsageRecord(Base, TenantOwned):
    __tablename__ = "ai_usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature = Column(String(100), nullable=False)
    purpose = Column(String(100), nullable=False)
    model = Column(String(100))
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    cost = Column(Numeric, nullable=False, server_default=text("0"))
    decision_log_id = Column(UUID(as_uuid=True), ForeignKey("ai_decision_log.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Part 18.24: who / which module / for what (e.g. an application) / ok or error / how long
    module = Column(String(50))
    user_id = Column(UUID(as_uuid=True))
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    status = Column(String(20), nullable=False, server_default=text("'ok'"))
    latency_ms = Column(Integer)


class AiUsageBudget(Base, TenantOwned):
    """One row per period (YYYY-MM). A call is refused once tokens or cost would exceed the
    limit (hard cutoff); `alert_pct` fires `ai.budget_alert` once per period."""

    __tablename__ = "ai_usage_budgets"
    __table_args__ = (UniqueConstraint("tenant_id", "period", name="ai_usage_budgets_tenant_period_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period = Column(String(7), nullable=False)
    token_limit = Column(Integer)  # NULL = unlimited
    cost_limit = Column(Numeric)
    alert_pct = Column(Integer, nullable=False, server_default=text("80"))
    alerted_at = Column(DateTime(timezone=True))
    exhausted_at = Column(DateTime(timezone=True))


class PromptEvalFixture(Base, TenantOwned):
    """Evaluation fixtures for the prompt registry: `expectations_json` {"must_include": [...],
    "must_not_include": [...], "json_keys": [...]} checked against a candidate prompt's output."""

    __tablename__ = "prompt_eval_fixtures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key = Column(String(100), nullable=False)
    name = Column(Text, nullable=False)
    input_text = Column(Text, nullable=False)
    expectations_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_result_json = Column(JSONB)
    last_run_at = Column(DateTime(timezone=True))
