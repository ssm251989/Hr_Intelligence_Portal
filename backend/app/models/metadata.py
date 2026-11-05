"""Metadata tables (docs/HRMS_COMPLETE_SPEC.txt Part 6): custom fields, forms/layouts,
masters/picklists, numbering sequences. `custom_field_defs.entity`/`form_layouts.entity`
accept any of `EXTENSIBLE_ENTITIES` below, but a `custom_fields JSONB` storage column only
actually EXISTS on the entities this app has real tables for today (candidates, job_roles,
applications) -- requisition/asset/ticket/separation/employee are all future-part tables
(Core HR, Helpdesk, ...); a def can be authored for them now (cheap, data-only, same
"seeded/definable ahead of the module that will consume it" pattern as several of Part 4's
own message_templates), it just has nowhere to actually store a value until that table
exists. See `platform/metadata/custom_fields.py`'s own module docstring for the validation
side of this.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

EXTENSIBLE_ENTITIES = (
    "employee", "candidate", "job", "application", "requisition", "asset", "ticket", "separation",
)
CUSTOM_FIELD_TYPES = (
    "text", "longtext", "number", "decimal", "date", "datetime", "bool", "picklist", "multipicklist",
    "user", "employee", "file", "email", "phone", "url", "currency", "formula", "lookup",
)
FORM_CONTEXTS = ("create", "edit", "view", "portal", "mobile")

# The 3 entities that actually have a live table + `custom_fields` JSONB column today --
# see this module's own docstring.
ENTITIES_WITH_CUSTOM_FIELD_STORAGE = ("candidate", "job", "application")


class CustomFieldDef(Base, TenantOwned):
    __tablename__ = "custom_field_defs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", "code", name="custom_field_defs_entity_code_uq"),
        CheckConstraint("entity IN (" + ",".join(f"'{e}'" for e in EXTENSIBLE_ENTITIES) + ")", name="custom_field_defs_entity_check"),
        CheckConstraint("type IN (" + ",".join(f"'{t}'" for t in CUSTOM_FIELD_TYPES) + ")", name="custom_field_defs_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity = Column(String(30), nullable=False)
    code = Column(String(100), nullable=False)
    label_i18n = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {"en": "...", "hi": "...", ...}
    type = Column(String(20), nullable=False)
    validation_json = Column(JSONB)  # {"min":..,"max":..,"pattern":..,"options":[...],"master_type_code":..}
    default = Column(JSONB)
    required_condition_jsonlogic = Column(JSONB)
    visible_condition_jsonlogic = Column(JSONB)
    section = Column(String(100))
    order = Column(Integer, nullable=False, server_default=text("0"))
    sensitive = Column(Boolean, nullable=False, server_default=text("false"))
    searchable = Column(Boolean, nullable=False, server_default=text("false"))
    reportable = Column(Boolean, nullable=False, server_default=text("true"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class FormLayout(Base, TenantOwned):
    __tablename__ = "form_layouts"
    __table_args__ = (
        CheckConstraint("entity IN (" + ",".join(f"'{e}'" for e in EXTENSIBLE_ENTITIES) + ")", name="form_layouts_entity_check"),
        CheckConstraint("context IN (" + ",".join(f"'{c}'" for c in FORM_CONTEXTS) + ")", name="form_layouts_context_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity = Column(String(30), nullable=False)
    context = Column(String(20), nullable=False)
    sections_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    role_ids = Column(ARRAY(UUID(as_uuid=True)))  # NULL means every role
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class MetaForm(Base, TenantOwned):
    """Free-standing forms (workflow tasks, exit interviews, onboarding, ...) -- named
    `MetaForm` (not `Form`) purely to avoid shadowing every WTForms/pydantic-adjacent
    "Form" name floating around Python code, same reasoning as Part 3's
    `anthropic_provider.py` avoiding the real `anthropic` package name."""

    __tablename__ = "forms"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="forms_tenant_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    schema_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ui_schema_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class MasterType(Base):
    """NOT TenantOwned -- the CATALOG of available picklist types (e.g. "designation"
    exists as a concept) is a platform-wide registry, same class as Part 3's connector
    purpose registry; the actual VALUES under a type (MasterValue below) are real
    per-tenant data."""

    __tablename__ = "master_types"

    code = Column(String(50), primary_key=True)
    name = Column(Text, nullable=False)
    hierarchical = Column(Boolean, nullable=False, server_default=text("false"))
    attributes_schema = Column(JSONB, server_default=text("'{}'::jsonb"))


class MasterValue(Base, TenantOwned):
    __tablename__ = "master_values"
    __table_args__ = (UniqueConstraint("tenant_id", "type_code", "code", name="master_values_tenant_type_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_code = Column(String(50), ForeignKey("master_types.code"), nullable=False)
    code = Column(String(100), nullable=False)
    label_i18n = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    parent_id = Column(UUID(as_uuid=True), ForeignKey("master_values.id"))
    attributes_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    sort = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    effective_from = Column(DateTime(timezone=True))
    effective_to = Column(DateTime(timezone=True))


class Sequence(Base, TenantOwned):
    __tablename__ = "sequences"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="sequences_tenant_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), nullable=False)
    pattern = Column(Text, nullable=False)
    scope = Column(String(20))  # "legal_entity" | "location" | NULL (tenant-wide)
    reset = Column(String(20), nullable=False, server_default=text("'never'"))
    current = Column(Integer, nullable=False, server_default=text("0"))
    current_period = Column(String(20))  # the YYYY (or FY string) `current` was last reset for


class I18nOverride(Base, TenantOwned):
    __tablename__ = "i18n_overrides"
    __table_args__ = (UniqueConstraint("tenant_id", "locale", "key", name="i18n_overrides_tenant_locale_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    locale = Column(String(10), nullable=False)
    key = Column(Text, nullable=False)
    value = Column(Text, nullable=False)


class FxRate(Base, TenantOwned):
    """A manually-maintained rate table (section 6's own "(amount, currency) with FX
    table") -- no live FX rate provider integration, real but simple, same scoping as
    every other "framework real, external feed not wired" gap in this build."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("tenant_id", "from_currency", "to_currency", "as_of_date", name="fx_rates_pair_date_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_currency = Column(String(3), nullable=False)
    to_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(18, 8), nullable=False)
    as_of_date = Column(DateTime(timezone=True), nullable=False)
