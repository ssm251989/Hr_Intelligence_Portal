"""Part 18.4: module unlock passcode -- per company, per module lock state.

`module_key` is a lockable area (app/platform/module_lock.py LOCKABLE) or "__all__" for the
one-passcode-for-everything row. The passcode is kept ONLY as a bcrypt hash; it is set with
`hrctl modules set-passcode` (prompted, never on the command line) or changed in Settings >
Modules (needs the current passcode). TenantOwned + RLS."""

import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class ModuleAccess(Base, TenantOwned):
    __tablename__ = "module_access"
    __table_args__ = (UniqueConstraint("tenant_id", "module_key", name="module_access_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_key = Column(String(50), nullable=False)
    passcode_hash = Column(Text)  # bcrypt; only on "__all__" (one passcode) or per-module rows
    unlocked_at = Column(DateTime(timezone=True))  # null = locked
    unlocked_by = Column(String(200))
    failed_attempts = Column(Integer, nullable=False, server_default=text("0"))
    lockout_until = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
