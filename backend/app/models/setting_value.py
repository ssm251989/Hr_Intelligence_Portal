"""Tenant tables backing the Settings Registry (docs/HRMS_COMPLETE_SPEC.txt Part 2 section
4) -- the registry itself (platform/settings/registry.py) is just schema; these two tables
hold the actual per-scope VALUES tenants set."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned
from app.platform.settings.registry import SCOPE_ORDER

_SCOPE_TYPE_CHECK = "scope_type IN (" + ",".join(f"'{s}'" for s in SCOPE_ORDER) + ")"


class SettingValue(Base, TenantOwned):
    __tablename__ = "setting_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "scope_type", "scope_id", name="setting_values_scope_uq"),
        CheckConstraint(_SCOPE_TYPE_CHECK, name="setting_values_scope_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)
    # "platform"/"plan" are never actually stored here (they're the registry's own
    # SettingDef.default and a future Part-13 plan-limits concern respectively) -- the
    # column still allows every SCOPE_ORDER value for forward compatibility with the
    # resolver's own generic walk.
    scope_type = Column(String(20), nullable=False, server_default=text("'tenant'"))
    # NULL exactly when scope_type='tenant' (the tenant itself needs no further scope id).
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    value_json = Column(JSONB, nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    updated_by = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))


class SettingValueHistory(Base, TenantOwned):
    """Append-only -- one row per SettingValue write, never updated or deleted (section H's
    audit discipline applies to settings changes same as everything else)."""

    __tablename__ = "setting_value_history"
    __table_args__ = (CheckConstraint(_SCOPE_TYPE_CHECK, name="setting_value_history_scope_type_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)
    scope_type = Column(String(20), nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    value_json = Column(JSONB, nullable=False)
    version = Column(Integer, nullable=False)
    updated_by = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
