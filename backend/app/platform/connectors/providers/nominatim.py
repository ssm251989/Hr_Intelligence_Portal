"""nominatim provider (Part 17.3) -- place name / PIN code -> coordinates through an
OpenStreetMap Nominatim server. The public server is the default when no connection is
routed for `geo.geocoding`; its usage policy (max 1 request/second, a real User-Agent) is
respected by the caller (app/platform/geo/service.py spaces requests and caches results).
A company can point this at its own Nominatim server via a connection."""

from typing import Optional

import httpx

from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "nominatim"
CAPABILITIES = ("Geocoder",)
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "base_url": {"type": "string", "default": "https://nominatim.openstreetmap.org"},
        "contact_email": {"type": "string", "description": "Sent with each request, as the server's policy asks"},
    },
}
SECRET_FIELDS = ()
DEFAULT_CONFIG = {"base_url": "https://nominatim.openstreetmap.org"}
TIMEOUT_SECONDS = 6.0


class NominatimAdapter:
    def __init__(self, config: dict, secrets: Optional[dict] = None):
        self.base_url = (config.get("base_url") or DEFAULT_CONFIG["base_url"]).rstrip("/")
        self.contact = config.get("contact_email") or ""

    def _headers(self) -> dict:
        agent = "hrms-platform/1.0"
        return {"User-Agent": f"{agent} ({self.contact})" if self.contact else agent, "Accept-Language": "en"}

    def geocode(self, query: str, *, country_codes: tuple[str, ...] = ("in",), postal_code: bool = False) -> Optional[dict]:
        """First match -> {"lat", "lng", "label", "country_code"}; None when nothing matches.
        Raises httpx errors on network trouble (the caller retries later)."""
        params = {"format": "jsonv2", "limit": 1, "addressdetails": 1}
        if country_codes:
            params["countrycodes"] = ",".join(c.lower() for c in country_codes)
        if postal_code:
            params["postalcode"] = query
        else:
            params["q"] = query
        resp = httpx.get(f"{self.base_url}/search", params=params, headers=self._headers(), timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        address = row.get("address") or {}
        return {"lat": float(row["lat"]), "lng": float(row["lon"]), "label": row.get("display_name"),
                "country_code": (address.get("country_code") or "").upper() or None}

    def test_connection(self) -> ProviderResult:
        try:
            hit = self.geocode("Chennai")
            return ProviderResult(success=hit is not None, error=None if hit else "no result for a known city")
        except Exception as exc:  # network / HTTP error
            return ProviderResult(success=False, error=str(exc))

    def health_check(self) -> ProviderResult:
        return self.test_connection()
