from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class BgvDocument(Base):
    __tablename__ = "bgv_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('aadhaar','pan','degree','experience')",
            name="bgv_documents_doc_type_check",
        ),
        CheckConstraint(
            "validation_status IN ('pending','valid','invalid','needs_review')",
            name="bgv_documents_validation_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    doc_type = Column(String(50))
    file_path = Column(Text)
    validation_status = Column(String(50), server_default=text("'pending'"))
    validator_output = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
