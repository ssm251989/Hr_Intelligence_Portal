"""Part 14 UX-standard tables (docs/HRMS_COMPLETE_SPEC.txt Part 14 sections 5-6):
per-user saved list views (filters, columns, sort -- optionally shared with a role) and
autosaved drafts of long forms. TenantOwned + RLS."""

import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class SavedView(Base, TenantOwned):
    """`config_json`: {"filters": {...}, "columns": [...], "sort": [{"field","dir"}], "page_size": 25}."""

    __tablename__ = "saved_views"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "list_key", "name", name="saved_views_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    list_key = Column(String(100), nullable=False)  # e.g. "helpdesk.tickets", "recruitment.candidates"
    name = Column(Text, nullable=False)
    config_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_default = Column(Boolean, nullable=False, server_default=text("false"))
    shared_role_name = Column(String(100))  # visible to everyone holding this role
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class FormDraft(Base, TenantOwned):
    __tablename__ = "form_drafts"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "form_key", "entity_ref", name="form_drafts_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    form_key = Column(String(100), nullable=False)  # e.g. "performance.review"
    entity_ref = Column(String(100), nullable=False, server_default=text("''"))  # the record being edited, "" for a new one
    data_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class TenantMedia(Base, TenantOwned):
    """Part 15 B: company-uploaded media -- the pre-joiner welcome video/GIF (`welcome.video`)
    and the 20-40s "Show me how" clips per page (`tour.<page>`, MP4/WebM with an optional
    `tour.<page>.gif` fallback). Files live under uploads/media/ (S3-compatible later)."""

    __tablename__ = "tenant_media"
    __table_args__ = (UniqueConstraint("tenant_id", "media_key", name="tenant_media_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_key = Column(String(120), nullable=False)
    file_path = Column(Text, nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    title = Column(Text)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class UserCelebration(Base, TenantOwned):
    """L-V3: confetti on offer signed / joiner marked joined is shown ONCE per user per event;
    this row is the "already celebrated" marker (so it holds across devices)."""

    __tablename__ = "user_celebrations"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "event_key", name="user_celebrations_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    event_key = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
