"""Tenant-scoped secrets (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 5) -- credentials for
this tenant's OWN connections (SMTP, AI provider keys the tenant brings, e-sign, ...). Part
3 is the first real consumer (connection config's secret_ref fields); this table exists
from Part 2 since the SecretStore mechanism itself (platform/secrets/store.py) is a Part 2
deliverable, identically shaped to the control-plane's own bootstrapping secrets table
(platform/tenancy/models_cp.py) but tenant-owned/RLS-protected instead."""

import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class SecretScope(Base, TenantOwned):
    __tablename__ = "secret_scopes"
    __table_args__ = (UniqueConstraint("tenant_id", "scope", name="secret_scopes_tenant_scope_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(100), nullable=False)
    wrapped_dek = Column(Text, nullable=False)


class Secret(Base, TenantOwned):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "scope", "ref", name="secrets_tenant_scope_ref_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(100), nullable=False)
    ref = Column(Text, nullable=False)
    backend = Column(String(20), nullable=False, server_default=text("'db_encrypted'"))
    ciphertext = Column(Text, nullable=False)
    key_version = Column(Integer, nullable=False, server_default=text("1"))
    created_by = Column(Text)
    rotated_at = Column(DateTime(timezone=True))
