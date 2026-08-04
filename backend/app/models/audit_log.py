from sqlalchemy import Column, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    action = Column(String(100))
    actor = Column(String(50))
    details = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
