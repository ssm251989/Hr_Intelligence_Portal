"""Part 17.3: one way to put a place on a map, used by every map in the app.

resolve(text) order:
  1. geo_cache  -- a previous answer for the same text (a manual fix always wins);
  2. the built-in table of India's ~300 largest cities (app/platform/geo/india_cities.py),
     matching the whole text, then each part of it ("Bangalore - Whitefield" -> Bengaluru);
  3. the geocoding connection (purpose `geo.geocoding`; OpenStreetMap Nominatim by default)
     -- only from a background task (lookup_later), never while a page waits.
Every point must fall inside the company's allowed countries (India by default, setting
`geo.countries`); anything else is reported as "not found" so a person can fix it.
"""

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.geo import GeoCacheEntry
from app.platform.geo.india_cities import ALIASES, CITIES, INDIA_BOUNDS

NOT_FOUND_RETRY = timedelta(days=7)
ONLINE_BATCH = 20  # most online lookups one background run makes
ONLINE_SPACING_SECONDS = 1.1  # Nominatim public policy: at most 1 request per second
_PIN = re.compile(r"\b(\d{6})\b")
_SPLIT = re.compile(r"[,/|()\-–]+|\s+near\s+|\s+in\s+")


@dataclass
class Place:
    lat: float
    lng: float
    label: str
    source: str  # manual | offline | nominatim


def normalise(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:255]


def _countries(db: Session, tenant) -> tuple[str, ...]:
    from app.platform.settings.resolver import SettingContext, SettingsService

    value = SettingsService(db).get("geo.countries", SettingContext(tenant=tenant)) or ["IN"]
    return tuple(str(c).upper() for c in value) or ("IN",)


def in_bounds(lat: float, lng: float, countries: Iterable[str], country_code: Optional[str] = None) -> bool:
    countries = tuple(countries)
    lat_min, lat_max, lng_min, lng_max = INDIA_BOUNDS
    inside_india = lat_min <= lat <= lat_max and lng_min <= lng <= lng_max
    if countries == ("IN",):
        return inside_india
    # another country was added: trust the geocoder's country code, or India's box
    return (country_code or "").upper() in countries or ("IN" in countries and inside_india)


def offline(text: str) -> Optional[Place]:
    key = normalise(text)
    if not key:
        return None
    candidates = [key] + [p.strip() for p in _SPLIT.split(key) if p.strip()]
    for part in candidates:
        city = ALIASES.get(part, part)
        if city in CITIES:
            lat, lng, state = CITIES[city]
            return Place(lat, lng, f"{city.title()}, {state}", "offline")
    # "Plot 12, Hitech City Hyderabad 500081" -> any known city name as a whole word
    for city in sorted(CITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(city)}\b", key):
            lat, lng, state = CITIES[city]
            return Place(lat, lng, f"{city.title()}, {state}", "offline")
    for alias, city in ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", key):
            lat, lng, state = CITIES[city]
            return Place(lat, lng, f"{city.title()}, {state}", "offline")
    return None


def _cached(db: Session, tenant, key: str) -> Optional[GeoCacheEntry]:
    return db.query(GeoCacheEntry).filter(GeoCacheEntry.tenant_id == tenant.tenant_id, GeoCacheEntry.query_key == key).first()


def _store(db: Session, tenant, key: str, *, place: Optional[Place], country_code: Optional[str] = None, actor: str = "system") -> None:
    row = _cached(db, tenant, key)
    if row is None:
        row = GeoCacheEntry(tenant_id=tenant.tenant_id, query_key=key)
        db.add(row)
    row.lat, row.lng = (place.lat, place.lng) if place else (None, None)
    row.label = place.label if place else None
    row.source = place.source if place else "none"
    row.country_code = country_code or ("IN" if place and place.source == "offline" else None)
    row.updated_by = actor
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def resolve(db: Session, tenant, text: Optional[str]) -> tuple[Optional[Place], str]:
    """-> (place, status). status: found | not_found (checked, nothing) | pending (not looked
    up online yet) | outside (found, but not in an allowed country) | empty (no text)."""
    key = normalise(text)
    if not key:
        return None, "empty"
    countries = _countries(db, tenant)
    row = _cached(db, tenant, key)
    if row is not None and row.source != "none" and row.lat is not None:
        if in_bounds(row.lat, row.lng, countries, row.country_code):
            return Place(row.lat, row.lng, row.label or text or "", row.source), "found"
        return None, "outside"
    hit = offline(key)
    if hit is not None:
        _store(db, tenant, key, place=hit)
        return hit, "found"
    if row is not None and row.source == "none" and row.updated_at and datetime.now(timezone.utc) - row.updated_at < NOT_FOUND_RETRY:
        return None, "not_found"
    return None, "pending"


def set_manual(db: Session, tenant, text: str, *, lat: float, lng: float, label: Optional[str], actor: str) -> Place:
    countries = _countries(db, tenant)
    if not in_bounds(lat, lng, countries):
        raise ValueError("That point is outside the countries your company works in.")
    place = Place(lat, lng, label or text, "manual")
    _store(db, tenant, normalise(text), place=place, actor=actor)
    return place


def _geocoder(db: Session):
    """The connection routed for `geo.geocoding`, else the public Nominatim server when the
    company allows online lookups (setting `geo.online_lookup`)."""
    from app.platform.connectors.providers.nominatim import DEFAULT_CONFIG, NominatimAdapter
    from app.platform.connectors.router import ConnectorRouter

    resolved = ConnectorRouter(db).try_resolve("geo.geocoding")
    if resolved is not None and resolved.connection.provider_code == "nominatim":
        return NominatimAdapter(resolved.connection.config_json or {})
    return NominatimAdapter(DEFAULT_CONFIG)


def online_allowed(db: Session, tenant) -> bool:
    from app.platform.settings.resolver import SettingContext, SettingsService

    return bool(SettingsService(db).get("geo.online_lookup", SettingContext(tenant=tenant)))


def lookup_later(tenant_id, slug: str, isolation: str, texts: list[str]) -> None:
    """Background task: look up to ONLINE_BATCH unknown places through the geocoding
    connection, one per ~second, caching every answer (a miss too). Network errors leave the
    text uncached so the next map view tries again."""
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp = ControlPlaneSessionLocal()
    try:
        tenant_row = cp.get(Tenant, tenant_id)
    finally:
        cp.close()
    if tenant_row is None:
        return
    ctx = TenantContext(tenant_id=tenant_id, slug=slug, isolation=isolation)
    with tenant_context(tenant_id, slug, isolation):
        db = tenant_session(tenant_row)
        try:
            if not online_allowed(db, ctx):
                return
            countries = _countries(db, ctx)
            geocoder = _geocoder(db)
            done = 0
            for text in dict.fromkeys(normalise(t) for t in texts if normalise(t)):
                if done >= ONLINE_BATCH:
                    break
                if resolve(db, ctx, text)[1] != "pending":
                    continue
                pin = _PIN.search(text)
                try:
                    hit = geocoder.geocode(pin.group(1) if pin and len(text) <= 8 else text,
                                           country_codes=tuple(c.lower() for c in countries), postal_code=bool(pin and len(text) <= 8))
                except Exception:
                    done += 1
                    time.sleep(ONLINE_SPACING_SECONDS)
                    continue
                if hit and in_bounds(hit["lat"], hit["lng"], countries, hit.get("country_code")):
                    _store(db, ctx, text, place=Place(hit["lat"], hit["lng"], hit.get("label") or text, "nominatim"), country_code=hit.get("country_code"))
                else:
                    _store(db, ctx, text, place=None)
                done += 1
                time.sleep(ONLINE_SPACING_SECONDS)
        finally:
            db.close()
