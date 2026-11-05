"""Part 17.3: geocoding cache. One row per place text a company has asked about ("Hyderabad",
"Bangalore - Whitefield", "560066") with where it was found, or that it wasn't. `source`:
manual (someone fixed it on a map) > offline (built-in city table) > nominatim (the
geocoding connection) > none (not found; retried after a while). TenantOwned + RLS."""

import uuid

from sqlalchemy import Column, DateTime, Float, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class GeoCacheEntry(Base, TenantOwned):
    __tablename__ = "geo_cache"
    __table_args__ = (UniqueConstraint("tenant_id", "query_key", name="geo_cache_query_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_key = Column(String(255), nullable=False)  # normalised place text
    label = Column(Text)  # what it resolved to, e.g. "Hyderabad, Telangana"
    lat = Column(Float)
    lng = Column(Float)
    country_code = Column(String(2))
    source = Column(String(20), nullable=False)
    updated_by = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
