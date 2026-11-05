"""Part 19.1: which modules a company uses (app/platform/module_registry.py).

One row per company + module: off -> pending (requested, waiting for the activation code from
CTD Techs) -> active. No row = off. Turning a module off needs no code; turning it on again
needs a new one. TenantOwned + RLS."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

MODULE_STATUSES = ("off", "pending", "active")


class CompanyModule(Base, TenantOwned):
    __tablename__ = "company_modules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="company_modules_key_uq"),
        CheckConstraint("status IN ('off','pending','active')", name="company_modules_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_key = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'off'"))
    requested_at = Column(DateTime(timezone=True))
    requested_by = Column(String(200))
    activated_at = Column(DateTime(timezone=True))
    activated_by = Column(String(200))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
