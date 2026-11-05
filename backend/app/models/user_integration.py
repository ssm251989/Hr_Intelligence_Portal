from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class UserIntegration(Base, TenantOwned):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="user_integrations_user_id_provider_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider = Column(String(50), nullable=False)
    # Encrypted credential blob. For Google/DocuSign this is a long-lived refresh token;
    # LinkedIn's self-serve apps don't get one, so for provider='linkedin' this holds the
    # short-lived (~60 day) access token instead -- see expires_at below.
    refresh_token = Column(Text, nullable=False)
    connected_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Only meaningful for providers whose credential actually expires (LinkedIn). Null for
    # Google/DocuSign refresh-token connections.
    expires_at = Column(DateTime(timezone=True))
    # Provider-specific extras that don't warrant their own column, e.g. LinkedIn's
    # {"member_urn": "urn:li:person:..."} needed to construct post authorship.
    provider_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
