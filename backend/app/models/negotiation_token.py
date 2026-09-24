from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class NegotiationToken(Base):
    """One recipient's session in the interviewer-first, double-blind pick-2-of-3
    scheduling negotiation (app/interview_scheduling/negotiation.py) -- the flow
    auto-triggered when an application's status becomes Shortlisted. One row per
    (application, role, interviewer_user_id, round_day): the 3 canned times for that
    round_day (see negotiation.py _slot_times_for_day) are shown as checkboxes on the
    linked page, and the recipient must pick exactly 2 (or decline) in one submission --
    unlike InterviewConfirmationToken's single immediate click-is-final link, but also
    unlike this table's own original shape (one row per clickable link: 3 slot-marking
    rows + a separate not_available/done row each), replaced because pick-2-of-3 is one
    combined submission, not a sequence of individual marks.

    Used for both sides of the negotiation, distinguished by `role`: "interviewer" (one per
    candidate interviewer the pool is walked to, for one offered day) and "candidate" (one
    per application, offering the SAME 3 canned times independently -- blind to which 2 the
    interviewer picked). `interviewer_user_id` is always the relevant interviewer either
    way -- who this row is waiting on for role="interviewer", or who to invite to the
    calendar event once role="candidate" resolves.

    There is only ever one live (not yet invalidated) row per (application, role,
    interviewer, round_day) at a time; a new one only starts once the previous one resolves
    (declined, re-prompted after a no-overlap defensive case, or superseded on the one
    retry day).

    duration_minutes/tracker_path are snapshotted the same way InterviewConfirmationToken
    already does -- a submission days later, or the eventual calendar event, must reflect
    what was actually offered and which tracker file to update, not whatever
    interview_scheduling_settings has since changed to.
    """

    __tablename__ = "negotiation_tokens"
    __table_args__ = (
        CheckConstraint("role IN ('interviewer','candidate')", name="negotiation_tokens_role_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False)
    role = Column(Text, nullable=False)
    interviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # The recruiter/hiring manager who triggered this negotiation (whose Google account
    # sends every outbound email in it) -- snapshotted so a submission resolved
    # asynchronously, possibly days later, still knows whose account to send the *next*
    # step's email from without needing that person to be the one submitting.
    actor_email = Column(Text, nullable=False)
    candidate_name = Column(Text)
    job_title = Column(Text)
    interviewer_name = Column(Text)
    # The Interviewer Pool sheet's Mails-tab address for interviewer_name, captured at
    # offer-send time (see tracker.email_for_interviewer) and carried forward through the
    # candidate round -- this, not a User row, is what _finalize sends the final .ics
    # confirmation to, since a pool interviewer is never required to have a User account.
    interviewer_email = Column(Text)
    round_day = Column(Date, nullable=False)
    duration_minutes = Column(Integer, server_default=text("60"))
    tracker_path = Column(Text)
    token = Column(Text, nullable=False, unique=True)
    # Populated on a valid (exactly-2) submission -- a JSON list of the 2 chosen slots' ISO
    # timestamps. NULL while pending; also NULL after a decline (distinguished from
    # "pending" by responded_at being set) -- see this table's own docstring above for the
    # three states this column + responded_at together represent.
    selected_slots = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    invalidated_at = Column(DateTime(timezone=True), nullable=True)
