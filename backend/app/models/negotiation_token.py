from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class NegotiationToken(Base):
    """One link in the interviewer-first scheduling negotiation (app/interview_scheduling/
    negotiation.py) -- the flow auto-triggered when an application's status becomes
    Shortlisted. Unlike InterviewConfirmationToken (one link = one immediate, final,
    single-use action), a BATCH of these lets its owner click more than one "slot" link to
    mark several options available before a "done" link actually commits them, or a
    "not_available" link declines the whole batch.

    Used for both sides of the negotiation, distinguished by `role`: "interviewer" batches
    (one per candidate interviewer the pool is walked to, for one offered day) and
    "candidate" batches (one per application, offering exactly the slots the interviewer
    just confirmed). `interviewer_user_id` is always the relevant interviewer either way --
    who the batch is waiting on for role="interviewer", or who to invite to the calendar
    event once role="candidate" resolves.

    A "batch" is every row sharing (application_id, role, interviewer_user_id, round_day)
    that isn't yet invalidated -- there is only ever one live batch per (application, role,
    interviewer) at a time; a new one only starts once the previous one resolves (declined,
    or superseded on the one retry day).

    duration_minutes/tracker_path are snapshotted the same way InterviewConfirmationToken
    already does -- a click days later, or the eventual calendar event, must reflect what
    was actually offered and which tracker file to update, not whatever
    interview_scheduling_settings has since changed to.
    """

    __tablename__ = "negotiation_tokens"
    __table_args__ = (
        CheckConstraint("role IN ('interviewer','candidate')", name="negotiation_tokens_role_check"),
        CheckConstraint("kind IN ('slot','not_available','done')", name="negotiation_tokens_kind_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False)
    role = Column(Text, nullable=False)
    interviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # The recruiter/hiring manager who triggered this negotiation (whose Google account
    # sends every outbound email in it) -- snapshotted so a click resolved asynchronously,
    # possibly days later, still knows whose account to send the *next* step's email from
    # without needing that person to be the one clicking.
    actor_email = Column(Text, nullable=False)
    candidate_name = Column(Text)
    job_title = Column(Text)
    interviewer_name = Column(Text)
    round_day = Column(Date, nullable=False)
    kind = Column(Text, nullable=False)
    slot_time = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Integer, server_default=text("60"))
    tracker_path = Column(Text)
    token = Column(Text, nullable=False, unique=True)
    marked_available = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    invalidated_at = Column(DateTime(timezone=True), nullable=True)
