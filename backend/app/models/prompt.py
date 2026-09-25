"""Prompt registry (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 4: "Prompt texts in a
prompt registry (versioned, tenant-overridable) - not in code"). Same versioned
draft->published lifecycle as Part 4's `message_templates` / Part 7's `letter_templates`
-- `app/recruitment/prompt_registry.py`. Seeded with each migrated `ai_services/*.py`
call site's CURRENT system prompt text as its published v1 (see `hrctl.seed_prompts`), so
migrating a call site onto this registry changes nothing by default -- only makes the
prompt text tenant-editable going forward."""

import uuid

from sqlalchemy import Column, DateTime, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class PromptTemplate(Base, TenantOwned):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "version", name="prompt_templates_tenant_key_version_uq"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)  # e.g. "recruitment.candidate_ranking"
    name = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(Text, nullable=False, server_default=text("'draft'"))
    purpose = Column(Text)  # the ai.gateway purpose this prompt is used with, e.g. "llm.judgment"
    system_prompt = Column(Text, nullable=False)
    variables_schema_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
