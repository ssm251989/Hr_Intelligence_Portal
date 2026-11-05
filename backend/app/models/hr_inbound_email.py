from sqlalchemy import Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class HrInboundEmail(Base, TenantOwned):
    """One email fetched from the shared HR mailbox's inbox by the 30-minute IMAP poll
    (app/integrations/imap_poll.py) -- logged here whether or not it could be matched to a
    real candidate, so recruiters have one place (the HR Inbox List) to see every incoming
    message. A match (by From address against Candidate.email) also gets surfaced on that
    candidate's existing Activity timeline via a normal audit_log entry -- this table is
    not itself read by that timeline, it's the durable record + the unmatched-mail backlog.

    message_id is the email's own Message-ID header -- the poll's dedup key across ticks,
    independent of (and a second line of defense alongside) the imap_last_uid checkpoint on
    HrIntegration.
    """

    __tablename__ = "hr_inbound_emails"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    from_address = Column(Text, nullable=False)
    to_address = Column(Text, nullable=True)
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    # The email's own Date header -- when the sender actually sent it, distinct from
    # created_at below (when this app's poll actually fetched/stored it).
    received_at = Column(DateTime(timezone=True), nullable=True)
    message_id = Column(Text, nullable=True, unique=True)
    matched_candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=True)
    matched_application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=True)
    # Part 22.2: sender name + reply headers (for matching), which rule linked it, candidates when several match
    from_name = Column(Text)
    in_reply_to = Column(Text)
    references_header = Column(Text)
    match_rule = Column(Text)  # email | alt_email | name | thread | manual
    match_suggestions_json = Column(JSONB)
    read_at = Column(DateTime(timezone=True))  # Part 22.3: first opened by HR (unread = bold)
    read_by = Column(Text)
    # Part 17.7: what the reply is about + whether someone still has to act on it
    topic = Column(Text)  # interview_time | documents | question | offer | withdrawal | other
    summary = Column(Text)  # one line (AI when switched on, else taken from the email)
    summary_source = Column(Text)  # ai | text
    status = Column(Text, nullable=False, server_default=text("'needs_action'"))  # needs_action | done
    done_at = Column(DateTime(timezone=True))
    done_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
