"""Part 17.13: idempotency keys -- the first response to a create request sent with an
`Idempotency-Key` header is kept for 24h and replayed for the same key, so a double click or
a network retry never creates the same record twice. TenantOwned + RLS."""

import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class IdempotencyKey(Base, TenantOwned):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="idempotency_keys_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(200), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(Text, nullable=False)
    status_code = Column(Integer, nullable=False)
    body = Column(Text)
    content_type = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
