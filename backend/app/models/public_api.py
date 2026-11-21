"""Part 30.2: public APIs + webhooks -- a company's own systems call the agents (api_keys, api_usage) and hear
what happened (webhook_subscriptions, webhook_deliveries). TenantOwned + RLS: a key or a subscription never sees
another company's rows."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

SCOPES = ("screening", "jobs", "candidates", "scheduling", "cards", "sensitive")
MODES = ("live", "test")


class ApiKey(Base, TenantOwned):
    __tablename__ = "api_keys"
    __table_args__ = (CheckConstraint("mode IN ('live', 'test')", name="api_keys_mode_check"),
                      Index("ix_api_keys_prefix", "prefix", unique=True))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    prefix = Column(String(24), nullable=False)  # "hra_live_ab12cd34" -- shown in the list, identifies the key
    secret_hash = Column(String(64), nullable=False)  # SHA-256 of the whole key; the key itself is shown once
    scopes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    mode = Column(String(4), nullable=False, server_default=text("'live'"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # the key acts as this person
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))


class ApiUsage(Base, TenantOwned):
    """One row per call -- per-call pricing and the usage chart on the Developers page."""

    __tablename__ = "api_usage"
    __table_args__ = (Index("ix_api_usage_key_created", "api_key_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"))
    method = Column(String(10), nullable=False)
    endpoint = Column(String(200), nullable=False)  # the route template, e.g. /applications/{id}
    status_code = Column(Integer, nullable=False)
    ms = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WebhookSubscription(Base, TenantOwned):
    __tablename__ = "webhook_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(Text, nullable=False)  # https only (checked on save)
    events = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    scopes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # "sensitive" -> figures in payloads
    secret_enc = Column(Text, nullable=False)  # signing secret, encrypted (app.core.crypto); shown once at creation
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WebhookDelivery(Base, TenantOwned):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (CheckConstraint("status IN ('pending', 'delivered', 'failed')", name="webhook_deliveries_status_check"),
                      Index("ix_webhook_deliveries_due", "status", "next_at"),
                      Index("ix_webhook_deliveries_sub_created", "subscription_id", "created_at"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False)
    event = Column(String(60), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(10), nullable=False, server_default=text("'pending'"))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_status = Column(Integer)  # the receiver's HTTP status (None = no answer)
    last_error = Column(Text)
    next_at = Column(DateTime(timezone=True), server_default=text("now()"))
    delivered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
