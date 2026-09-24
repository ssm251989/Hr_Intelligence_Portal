"""Tenant tables for the Communication Engine (docs/HRMS_COMPLETE_SPEC.txt Part 4
section 1)."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

TEMPLATE_CHANNELS = ("email", "in_app", "sms", "whatsapp", "chat", "push")
TEMPLATE_STATUSES = ("draft", "published", "archived")
DIGEST_MODES = ("none", "hourly", "daily")
OUTBOUND_STATUSES = ("queued", "sending", "sent", "delivered", "bounced", "failed", "suppressed")
SUPPRESSION_REASONS = ("bounce", "unsubscribe", "complaint")


class BrandTheme(Base, TenantOwned):
    __tablename__ = "brand_themes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    logo_file_id = Column(UUID(as_uuid=True))
    primary_color = Column(String(9))
    secondary_color = Column(String(9))
    gradient_from = Column(String(9))
    gradient_to = Column(String(9))
    font_family = Column(Text)
    email_footer_html = Column(Text)
    legal_disclaimer = Column(Text)
    social_links_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    is_default = Column(Boolean, nullable=False, server_default=text("false"))
    legal_entity_id = Column(UUID(as_uuid=True))


class MessageLayout(Base, TenantOwned):
    __tablename__ = "message_layouts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(String(20), nullable=False)
    name = Column(Text, nullable=False)
    html_shell = Column(Text)
    text_shell = Column(Text)
    theme_id = Column(UUID(as_uuid=True), ForeignKey("brand_themes.id"))


class MessageTemplate(Base, TenantOwned):
    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "locale", "version", name="message_templates_key_locale_version_uq"),
        CheckConstraint("channel IN (" + ",".join(f"'{c}'" for c in TEMPLATE_CHANNELS) + ")", name="message_templates_channel_check"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in TEMPLATE_STATUSES) + ")", name="message_templates_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(Text, nullable=False)
    channel = Column(String(20), nullable=False)
    locale = Column(String(10), nullable=False, server_default=text("'en'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    subject_tpl = Column(Text)
    html_tpl = Column(Text)
    text_tpl = Column(Text)
    sms_tpl = Column(Text)
    whatsapp_provider_template_name = Column(Text)
    variables_schema_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    layout_id = Column(UUID(as_uuid=True), ForeignKey("message_layouts.id"))
    attachments_spec_json = Column(JSONB)
    published_by = Column(Text)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class NotificationRule(Base, TenantOwned):
    __tablename__ = "notification_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    event_type = Column(String(100), nullable=False)
    condition_jsonlogic = Column(JSONB)
    recipients_json = Column(JSONB, nullable=False)
    channels = Column(ARRAY(String), nullable=False, server_default=text("'{}'"))
    template_key = Column(Text, nullable=False)
    delay_spec = Column(JSONB)
    quiet_hours_respect = Column(Boolean, nullable=False, server_default=text("true"))
    digest_mode = Column(String(20), nullable=False, server_default=text("'none'"))
    priority = Column(Integer, nullable=False, server_default=text("1"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("digest_mode IN (" + ",".join(f"'{d}'" for d in DIGEST_MODES) + ")", name="notification_rules_digest_mode_check"),
    )


class NotificationPreference(Base, TenantOwned):
    __tablename__ = "notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    candidate_id = Column(UUID(as_uuid=True), nullable=True)
    channel = Column(String(20), nullable=False)
    event_group = Column(String(100), nullable=False)
    opted_in = Column(Boolean, nullable=False, server_default=text("true"))
    quiet_hours_json = Column(JSONB)


class OutboundMessage(Base, TenantOwned):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in OUTBOUND_STATUSES) + ")", name="outbound_messages_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("notification_rules.id"))
    template_id = Column(UUID(as_uuid=True), ForeignKey("message_templates.id"))
    template_version = Column(Integer)
    channel = Column(String(20), nullable=False)
    purpose = Column(String(100))
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"))
    to_addresses = Column(ARRAY(String), nullable=False, server_default=text("'{}'"))
    cc_addresses = Column(ARRAY(String), server_default=text("'{}'"))
    bcc_addresses = Column(ARRAY(String), server_default=text("'{}'"))
    subject = Column(Text)
    body_ref = Column(Text)  # the rendered body itself -- see this module's own docstring
    status = Column(String(20), nullable=False, server_default=text("'queued'"))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    provider_message_id = Column(Text)
    thread_key = Column(Text)
    related_entity_type = Column(String(50))
    related_entity_id = Column(UUID(as_uuid=True))
    error = Column(Text)
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class InboundMessage(Base, TenantOwned):
    __tablename__ = "inbound_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"))
    from_address = Column(Text, nullable=False)
    to_address = Column(Text)
    subject = Column(Text)
    message_id = Column(Text)
    in_reply_to = Column(Text)
    references_header = Column(Text)
    thread_key = Column(Text)
    body_ref = Column(Text)
    attachments_json = Column(JSONB)
    routed_handler = Column(String(100))
    routed_entity_type = Column(String(50))
    routed_entity_id = Column(UUID(as_uuid=True))
    status = Column(String(20), nullable=False, server_default=text("'unmatched'"))
    received_at = Column(DateTime(timezone=True), server_default=text("now()"))


class SuppressionListEntry(Base, TenantOwned):
    __tablename__ = "suppression_list"
    __table_args__ = (
        UniqueConstraint("tenant_id", "address", name="suppression_list_tenant_address_uq"),
        CheckConstraint("reason IN (" + ",".join(f"'{r}'" for r in SUPPRESSION_REASONS) + ")", name="suppression_list_reason_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address = Column(Text, nullable=False)
    reason = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
