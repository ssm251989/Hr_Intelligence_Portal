from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

# "career_portal"/"manual" are populated by the two existing creation paths (public apply,
# internal resume upload); "local_import" by the Import wizard's "Import from Local" step
# (bulk-selecting several resume files at once -- see app/candidates/router.py
# upload_resume's source param). linkedin/naukri/indeed/monster/shine are defined now -- so
# the column never needs a migration when those sourcing integrations go live -- but
# nothing writes them yet. "agency" = sent in through the agency portal (Part 15.6).
CANDIDATE_SOURCES = (
    "career_portal", "manual", "local_import", "agency",
    "linkedin", "naukri", "indeed", "monster", "shine",
)


class Candidate(Base, TenantOwned):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "source IN (" + ",".join(f"'{s}'" for s in CANDIDATE_SOURCES) + ")",
            name="candidates_source_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    full_name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    location = Column(String(255))
    resume_path = Column(Text)
    photo_path = Column(Text)
    parsed_fields = Column(JSONB)
    # Part 6 section 1 -- values keyed by custom_field_defs.code for entity="candidate";
    # validated server-side against the tenant's own active defs (platform.metadata.
    # custom_fields.validate_custom_fields), never trusted as-is from a client payload.
    custom_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    source = Column(String(50), nullable=False, server_default=text("'manual'"))
    # "Suitable For" suggestion (Part B) -- the best-fitting *published* job this candidate
    # was ever automatically compared against, independent of whichever job(s) they actually
    # applied for. Purely informational: nothing here ever changes an Application's
    # job_role_id. Both null until app/screening/suitability.py's automatic hook (right
    # after a resume is parsed) finds at least one published job to compare against.
    suitable_job_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"), nullable=True)
    suitable_job_score = Column(Numeric, nullable=True)
    # Part 17.5/17.8: salary & joining details (careers form, resume, or the candidate's own
    # "Salary & joining details" form) and what the scoring factors read.
    current_ctc = Column(Numeric)
    expected_ctc = Column(Numeric)
    notice_period_days = Column(Integer)
    willing_to_relocate = Column(Boolean)
    languages = Column(JSONB)
    # Part 17.13: duplicate detection -- the resume file's SHA-256, and the earlier record of the
    # same person (same email / phone / file). Linked, never merged or deleted automatically.
    resume_sha256 = Column(String(64), index=True)
    duplicate_of_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"))
    tags = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))  # Part 18.10: lower-case labels HR adds
    # Part 17.15: in the Recycle bin (hidden everywhere; see app/recruitment/removal.py)
    deleted_at = Column(DateTime(timezone=True), index=True)
    deleted_by = Column(String(200))
    delete_reason = Column(String(30))
    delete_note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
