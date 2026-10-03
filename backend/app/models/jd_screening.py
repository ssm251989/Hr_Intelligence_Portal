"""Part 19.1: screening without the Jobs module -- candidates scored against a job description
pasted or uploaded on the Screening page (no job record). TenantOwned + RLS."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class JdScreening(Base, TenantOwned):
    __tablename__ = "jd_screenings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    jd_text = Column(Text, nullable=False)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class JdScreeningResult(Base, TenantOwned):
    __tablename__ = "jd_screening_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screening_id = Column(UUID(as_uuid=True), ForeignKey("jd_screenings.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    match_score = Column(Integer)
    recommendation = Column(String(30))
    error = Column(Text)
    result_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
