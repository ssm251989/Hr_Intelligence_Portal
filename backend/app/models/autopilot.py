"""Part 26: HR Autopilot -- what the automatic agents did (agent_activity) and where they left off
(autopilot_state: the event cursor, the last briefing per person, ...)."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

AUTOPILOT_AGENTS = ("watchdog", "screening", "sourcing", "scheduling", "salary", "documents", "bgv", "offer", "onboarding", "exit", "briefing")
# done: routine step taken | decided: an outcome decided by a company rule | proposed: approval card raised
# escalated: a person was told something is stuck | skipped: looked, nothing to do / not allowed | failed: error
OUTCOMES = ("done", "decided", "proposed", "escalated", "skipped", "failed")
TRIGGERS = ("event", "schedule", "manual")


def _in(col: str, values: tuple) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class AgentActivity(Base, TenantOwned):
    __tablename__ = "agent_activity"
    __table_args__ = (
        CheckConstraint(_in("agent", AUTOPILOT_AGENTS), name="agent_activity_agent_check"),
        CheckConstraint(_in("outcome", OUTCOMES), name="agent_activity_outcome_check"),
        CheckConstraint(_in("trigger", TRIGGERS), name="agent_activity_trigger_check"),
        Index("ix_agent_activity_created_at", "created_at"),
        Index("ix_agent_activity_entity", "entity_type", "entity_id", "action"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent = Column(String(20), nullable=False)
    trigger = Column(String(10), nullable=False)
    event = Column(String(100))  # the audit action that woke the agent, for trigger=event
    action = Column(String(60), nullable=False)  # e.g. auto_shortlist, salary_rule_approve, escalate_stale_screened
    outcome = Column(String(10), nullable=False)
    rule = Column(String(100))  # the setting that allowed a decision
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    summary = Column(Text, nullable=False)  # one plain sentence for the activity feed
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AutopilotState(Base, TenantOwned):
    __tablename__ = "autopilot_state"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="autopilot_state_tenant_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), nullable=False)
    value_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))
