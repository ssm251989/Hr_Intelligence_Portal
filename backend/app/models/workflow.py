"""Workflow & Approval Engine tables (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 1-2)."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

DEFINITION_STATUSES = ("draft", "published", "retired")
INSTANCE_STATUSES = ("running", "completed", "cancelled", "failed")
STEP_STATUSES = ("pending", "approved", "rejected", "skipped", "sent_back", "cancelled", "failed")


class WorkflowDefinition(Base, TenantOwned):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "version", name="workflow_definitions_key_version_uq"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in DEFINITION_STATUSES) + ")", name="workflow_definitions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    module = Column(String(50))
    version = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    trigger_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    graph_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_by = Column(Text)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WorkflowInstance(Base, TenantOwned):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in INSTANCE_STATUSES) + ")", name="workflow_instances_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id = Column(UUID(as_uuid=True), ForeignKey("workflow_definitions.id"), nullable=False)
    definition_version = Column(Integer, nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'running'"))
    context_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    current_node_id = Column(String(100))
    started_by = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=text("now()"))
    ended_at = Column(DateTime(timezone=True))


class WorkflowStep(Base, TenantOwned):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in STEP_STATUSES) + ")", name="workflow_steps_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id"), nullable=False)
    node_id = Column(String(100), nullable=False)
    node_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    assignee_user_id = Column(UUID(as_uuid=True))
    due_at = Column(DateTime(timezone=True))
    acted_by = Column(Text)
    action = Column(String(30))
    comment = Column(Text)
    payload_json = Column(JSONB)
    started_at = Column(DateTime(timezone=True), server_default=text("now()"))
    ended_at = Column(DateTime(timezone=True))


class WorkflowTimer(Base, TenantOwned):
    """Timers a live Celery beat schedule would poll (docs/build_log.md's own Part 5 note
    on why nothing auto-flushes these yet -- same documented gap as Part 4's quiet-hours/
    digest holds and Part 2's own TenantTask). `process_due_timers()` (platform/workflow/
    engine.py) is real and tested directly; nothing calls it on a schedule yet."""

    __tablename__ = "workflow_timers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id"), nullable=False)
    step_id = Column(UUID(as_uuid=True), ForeignKey("workflow_steps.id"))
    kind = Column(String(20), nullable=False)  # "wait" | "sla_escalation" | "reminder"
    fires_at = Column(DateTime(timezone=True), nullable=False)
    payload_json = Column(JSONB)
    processed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
