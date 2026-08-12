from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

# "career_portal"/"manual" are populated by the two existing creation paths (public apply,
# internal resume upload); "local_import" by the Import wizard's "Import from Local" step
# (bulk-selecting several resume files at once -- see app/candidates/router.py
# upload_resume's source param). linkedin/naukri/indeed/monster/shine are defined now -- so
# the column never needs a migration when those sourcing integrations go live -- but
# nothing writes them yet.
CANDIDATE_SOURCES = (
    "career_portal", "manual", "local_import",
    "linkedin", "naukri", "indeed", "monster", "shine",
)


class Candidate(Base):
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
    source = Column(String(50), nullable=False, server_default=text("'manual'"))
    # "Suitable For" suggestion (Part B) -- the best-fitting *published* job this candidate
    # was ever automatically compared against, independent of whichever job(s) they actually
    # applied for. Purely informational: nothing here ever changes an Application's
    # job_role_id. Both null until app/screening/suitability.py's automatic hook (right
    # after a resume is parsed) finds at least one published job to compare against.
    suitable_job_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"), nullable=True)
    suitable_job_score = Column(Numeric, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
