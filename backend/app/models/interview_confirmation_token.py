from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class InterviewConfirmationToken(Base, TenantOwned):
    """One candidate-facing confirmation link for one proposed interview slot (Part 3 --
    email + secure-link confirmation). Three of these are created per proposal run, one per
    slot a real interviewer was actually found free for (see
    app/interview_scheduling/confirmation.py propose_interview_slots) -- each independently
    valid until the candidate confirms one (which invalidates the other two via
    `invalidated_at`) or all expire.

    A token is usable only while `used_at` and `invalidated_at` are both null and
    `expires_at` is in the future -- see confirmation.py confirm_token for the exact check.
    """

    __tablename__ = "interview_confirmation_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False)
    token = Column(Text, nullable=False, unique=True)
    # Snapshotted at proposal time (rather than joined live through application_id) so a
    # confirmation click days later -- and the Interview Log row it updates -- always
    # reflects what the candidate was actually told, even if the candidate/job/tracker
    # since changed.
    candidate_name = Column(Text)
    job_title = Column(Text)
    interviewer_name = Column(Text)
    interviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    slot_time = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, server_default=text("60"))
    tracker_path = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    invalidated_at = Column(DateTime(timezone=True))
