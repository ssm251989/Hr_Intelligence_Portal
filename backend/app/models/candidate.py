from sqlalchemy import Column, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    full_name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    resume_path = Column(Text)
    parsed_fields = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
