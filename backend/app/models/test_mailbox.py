"""Part 20.2b: the TEST (dummy) email provider. Nothing here is a real mailbox -- the rows stand in for
Google Workspace / Microsoft 365 accounts until a real email-admin connection is set up, and emails the
app sends to these addresses are kept in `test_mailbox_messages` (Settings > Integrations > Test email
provider) instead of leaving the server (in development they also reach mailpit)."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class TestMailbox(Base, TenantOwned):
    __tablename__ = "test_mailboxes"
    __test__ = False  # not a pytest class
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','deleted')", name="test_mailboxes_status_check"),
        UniqueConstraint("tenant_id", "address", name="test_mailboxes_tenant_address_uq"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address = Column(Text, nullable=False)
    display_name = Column(Text)
    employee_id = Column(UUID(as_uuid=True))
    employee_code = Column(String(50))
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    quota = Column(String(40), nullable=False, server_default=text("'15 GB (dummy)'"))
    provider = Column(String(20), nullable=False, server_default=text("'TEST'"))
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True))


class TestMailboxMessage(Base, TenantOwned):
    __tablename__ = "test_mailbox_messages"
    __test__ = False

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mailbox_id = Column(UUID(as_uuid=True), ForeignKey("test_mailboxes.id", ondelete="CASCADE"), nullable=False)
    to_address = Column(Text, nullable=False)
    from_address = Column(Text)
    subject = Column(Text)
    body_text = Column(Text)
    body_html = Column(Text)
    template_key = Column(String(120))
    outbound_message_id = Column(UUID(as_uuid=True))
    received_at = Column(DateTime(timezone=True), server_default=text("now()"))
