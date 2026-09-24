"""Tenant tables for the Connections Framework (docs/HRMS_COMPLETE_SPEC.txt Part 3
section 3)."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

CONNECTION_STATUSES = ("draft", "active", "error", "disabled")


class Connection(Base, TenantOwned):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in CONNECTION_STATUSES) + ")", name="connections_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    provider_code = Column(String(50), nullable=False)
    capability = Column(ARRAY(String), nullable=False, server_default=text("'{}'"))
    config_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    secret_ref = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    last_tested_at = Column(DateTime(timezone=True))
    last_test_result = Column(JSONB)
    last_health_at = Column(DateTime(timezone=True))
    health_status = Column(String(20))
    owner_user_id = Column(UUID(as_uuid=True))
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ConnectionOAuthToken(Base, TenantOwned):
    __tablename__ = "connection_oauth_tokens"

    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"), primary_key=True)
    access_secret_ref = Column(Text)
    refresh_secret_ref = Column(Text)
    expires_at = Column(DateTime(timezone=True))
    scopes = Column(ARRAY(String), server_default=text("'{}'"))


class ConnectionRoute(Base, TenantOwned):
    __tablename__ = "connection_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purpose = Column(String(100), nullable=False)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"), nullable=False)
    priority = Column(Integer, nullable=False, server_default=text("1"))
    condition_jsonlogic = Column(JSONB)
    from_identity_json = Column(JSONB)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))


class ConnectionAttempt(Base, TenantOwned):
    """Not physically partitioned in this dev environment (spec: "partitioned" -- a
    production-scale/Part-13 concern); the column shape is what matters for the app code
    and is unaffected by whether the table itself is partitioned later."""

    __tablename__ = "connection_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id"), nullable=False)
    purpose = Column(String(100), nullable=False)
    operation = Column(String(50), nullable=False)
    request_meta = Column(JSONB)
    status = Column(String(20), nullable=False)
    latency_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
