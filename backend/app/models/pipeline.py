"""Configurable hiring pipeline (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 1) --
replaces the fixed status-enum lifecycle with tenant-editable stages. `hrctl.seed_pipeline`
seeds one default template whose stages reproduce `Application.APPLICATION_STATUSES`
exactly (see that seed function's own docstring for the parity mapping) -- proving pipeline
template parity without changing how `applications.status` transitions actually work
today (see docs/build_log.md's own Part 8 note on why the transition code itself isn't
retrofitted onto these stages in this pass)."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

PIPELINE_STAGE_CATEGORIES = (
    "applied", "screening", "assessment", "interview", "offer", "preboarding",
    "hired", "rejected", "withdrawn",
)


class PipelineTemplate(Base, TenantOwned):
    __tablename__ = "pipeline_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    is_default = Column(Boolean, nullable=False, server_default=text("false"))


class PipelineStage(Base, TenantOwned):
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", "code", name="pipeline_stages_template_code_uq"),
        CheckConstraint("category IN (" + ",".join(f"'{c}'" for c in PIPELINE_STAGE_CATEGORIES) + ")", name="pipeline_stages_category_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("pipeline_templates.id"), nullable=False)
    code = Column(Text, nullable=False)  # matches an Application.APPLICATION_STATUSES value for the default template
    name_i18n = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    order = Column(Integer, nullable=False, server_default=text("0"))
    category = Column(Text, nullable=False)
    sla_days = Column(Integer)
    entry_workflow_key = Column(Text)
    exit_workflow_key = Column(Text)
    required_fields = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    auto_actions_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    candidate_visible_name = Column(Text)
