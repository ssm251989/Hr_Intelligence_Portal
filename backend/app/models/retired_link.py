"""Fix 2026-10-04: a link whose record was deleted (e.g. the candidate was deleted permanently)
still gets a clear page ("This interview was cancelled") instead of "link not recognized".
Only a sha256 of the token is kept -- no personal data. TenantOwned + RLS."""

import hashlib
import uuid

from sqlalchemy import Column, DateTime, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


class RetiredLink(Base, TenantOwned):
    __tablename__ = "retired_links"
    __table_args__ = (UniqueConstraint("tenant_id", "token_hash", name="retired_links_hash_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash = Column(String(64), nullable=False)
    kind = Column(String(30), nullable=False)  # interview_negotiation | interview_confirmation
    reason = Column(String(30), nullable=False)  # cancelled
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
