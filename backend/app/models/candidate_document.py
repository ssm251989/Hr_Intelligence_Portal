"""Part 18.16/18.17: joining documents the candidate uploads after the salary is approved
(PAN, Aadhaar, certificates, payslips ...; the list is Settings > Hiring > Required documents).

check_level / check_output: the agent's check of each file (green ok / amber check / red problem
+ reasons). hr_status: pending | approved | reupload (HR asked for it again, hr_note says why).
Files live under uploads/joining-docs/<tenant>/ and are deleted with the candidate (17.15)."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class CandidateDocument(Base, TenantOwned):
    __tablename__ = "candidate_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_code = Column(String(60), nullable=False)
    label = Column(Text)
    file_path = Column(Text, nullable=False)  # "<tenant>/<uuid>.<ext>" under uploads/joining-docs
    original_name = Column(Text)
    content_type = Column(String(100))
    size_bytes = Column(Integer)
    check_level = Column(String(10))  # green | amber | red (null = not checked yet)
    check_output = Column(JSONB)
    hr_status = Column(String(20), nullable=False, server_default=text("'pending'"))
    hr_note = Column(Text)
    reviewed_by = Column(String(200))
    reviewed_at = Column(DateTime(timezone=True))
    uploaded_at = Column(DateTime(timezone=True), server_default=text("now()"))
