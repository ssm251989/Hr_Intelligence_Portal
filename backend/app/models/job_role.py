from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class JobRole(Base):
    __tablename__ = "job_roles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','ready_for_publishing','published','closed')",
            name="job_roles_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(String(255), nullable=False)
    department = Column(String(255))
    location = Column(String(255))
    experience_level = Column(String(100))
    skills = Column(JSONB)
    salary_band_min = Column(Numeric)
    salary_band_max = Column(Numeric)
    hiring_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    positions_count = Column(Integer, server_default=text("1"))
    jd_text = Column(Text)
    status = Column(String(50), server_default=text("'draft'"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
