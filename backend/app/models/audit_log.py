from sqlalchemy import Column, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        # Supports the Candidates List's Remarks column (see app/screening/service.py
        # describe_screening_audit_entry / app/candidates/router.py's latest-screening-entry
        # subquery) -- one "give me the latest matching action for this entity" lookup per
        # row, on List/export/dashboard queries that can run over hundreds of rows at once.
        Index("ix_audit_log_entity_type_entity_id_created_at", "entity_type", "entity_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    action = Column(String(100))
    actor = Column(String(50))
    details = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
