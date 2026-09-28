from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

JOB_ROLE_STATUSES = ("draft", "ready_for_publishing", "published", "closed", "on_hold")
JOB_TYPES = ("Full-time", "Part-time", "Contract")
EDUCATION_DEGREE_LEVELS = ("Any", "Bachelor's", "Master's", "PhD", "Diploma")


class JobRole(Base, TenantOwned):
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
        CheckConstraint(
            "education_degree_level IN ("
            + ",".join(f"'{level.replace(chr(39), chr(39) * 2)}'" for level in EDUCATION_DEGREE_LEVELS)
            + ") OR education_degree_level IS NULL",
            name="job_roles_education_degree_level_check",
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
    key_responsibilities = Column(Text)
    education_degree_level = Column(String(50))
    education_field = Column(String(255))
    preferred_certifications = Column(JSONB)
    salary_band_min = Column(Numeric)
    salary_band_max = Column(Numeric)
    hiring_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    positions_count = Column(Integer, server_default=text("1"))
    jd_text = Column(Text)
    status = Column(String(50), server_default=text("'draft'"))
    # Part 18.8: why/when it was closed by hand (filled / cancelled / business_hold / other)
    closed_at = Column(DateTime(timezone=True))
    close_reason = Column(String(30))
    close_note = Column(Text)
    job_type = Column(String(50), nullable=False, server_default=text("'Full-time'"))
    benefits = Column(Text)
    additional_notes = Column(Text)
    published_platforms = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    publish_settings = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    posting_url_naukri = Column(Text)
    posting_url_linkedin = Column(Text)
    # Part 8 section 1 -- nullable: unset uses the tenant's default PipelineTemplate.
    pipeline_template_id = Column(UUID(as_uuid=True), ForeignKey("pipeline_templates.id"))
    # Part 8 section 3 -- career-site knockout questions: [{"question": str, "disqualify_on": str}].
    knockout_questions_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Part 17.6: per-job shortlisting rules {threshold, max_size, auto_shortlist, undo_hours,
    # notify: [...]} -- empty = company defaults.
    shortlisting_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Set only when a real LinkedIn post was created via the API (see
    # app/jobs/router.py _try_post_to_linkedin) -- as opposed to posting_url_linkedin,
    # which is the manually-pasted fallback link used when there's no LinkedIn connection.
    linkedin_post_urn = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Part 6 section 1 -- see candidates.py's own custom_fields column comment.
    custom_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
