from sqlalchemy import Boolean, Column, Integer, Text

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class HrIntegration(Base, TenantOwned):
    """Singleton row (always id=1) holding the single shared, org-level mailbox ("CTDHR")
    every automated HR email in this app sends from, and now also polls for incoming mail --
    plain SMTP/IMAP credentials (universal across providers -- Gmail, Outlook, Yahoo,
    anything), not an OAuth connection. Calendar event creation is entirely separate and
    untouched: it still always uses the responsible recruiter/interviewer's own personal
    UserIntegration (Google OAuth), a completely different feature from this one.

    Same singleton-row pattern as InterviewSchedulingSettings/ScreeningSettings -- one
    small, rarely-changed config row. Null/absent SMTP or IMAP fields mean that side hasn't
    been configured yet via Settings; every caller treats that the same way they already
    treat "actor hasn't connected Google" -- skip gracefully, never a hard failure, since
    the real CTDHR mailbox may not exist yet.

    smtp_username/smtp_password are shared by IMAP too (same mailbox account, not separate
    credentials) -- imap_host/imap_port/use_ssl are the only IMAP-specific fields.
    """

    __tablename__ = "hr_integrations"

    id = Column(Integer, primary_key=True)

    # --- outgoing (SMTP) ---
    smtp_host = Column(Text, nullable=True)
    smtp_port = Column(Integer, nullable=True)
    use_tls = Column(Boolean, nullable=True)
    smtp_username = Column(Text, nullable=True)
    # Encrypted at rest (app.core.crypto), same approach as the old OAuth refresh token.
    smtp_password = Column(Text, nullable=True)
    from_address = Column(Text, nullable=True)
    # Optional -- set as Reply-To and BCC on every outgoing HR email when configured, a
    # no-op (neither header added) when left blank.
    hr_module_email = Column(Text, nullable=True)

    # --- incoming (IMAP) -- same mailbox, reuses smtp_username/smtp_password above ---
    imap_host = Column(Text, nullable=True)
    imap_port = Column(Integer, nullable=True)
    use_ssl = Column(Boolean, nullable=True)
    # The highest IMAP UID this mailbox has already processed -- the poll's own checkpoint
    # so a 30-minute tick only ever fetches what's new since the last one, never
    # reprocessing the same message twice. Null means "never polled yet" (first poll
    # imports the whole current inbox once, then starts checkpointing from there).
    imap_last_uid = Column(Integer, nullable=True)
