from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

JOB_ROLE_STATUSES = ("draft", "ready_for_publishing", "published", "closed", "on_hold")
JOB_TYPES = ("Full-time", "Part-time", "Contract")


class JobRole(Base):
    __tablename__ = "job_roles"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in JOB_ROLE_STATUSES) + ")",
            name="job_roles_status_check",
        ),
        CheckConstraint(
            "job_type IN (" + ",".join(f"'{t}'" for t in JOB_TYPES) + ")",
            name="job_roles_job_type_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(String(255), nullable=False)
    department = Column(String(255))
    location = Column(String(255))
    experience_min_years = Column(Numeric)
    experience_max_years = Column(Numeric)
    technical_skills_must_have = Column(JSONB)
    technical_skills_good_to_have = Column(JSONB)
    soft_skills_must_have = Column(JSONB)
    soft_skills_good_to_have = Column(JSONB)
    salary_band_min = Column(Numeric)
    salary_band_max = Column(Numeric)
    hiring_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    positions_count = Column(Integer, server_default=text("1"))
    jd_text = Column(Text)
    status = Column(String(50), server_default=text("'draft'"))
    job_type = Column(String(50), nullable=False, server_default=text("'Full-time'"))
    benefits = Column(Text)
    additional_notes = Column(Text)
    published_platforms = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    publish_settings = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    posting_url_naukri = Column(Text)
    posting_url_linkedin = Column(Text)
    # Set only when a real LinkedIn post was created via the API (see
    # app/jobs/router.py _try_post_to_linkedin) -- as opposed to posting_url_linkedin,
    # which is the manually-pasted fallback link used when there's no LinkedIn connection.
    linkedin_post_urn = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
