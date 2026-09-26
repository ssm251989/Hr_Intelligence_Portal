"""Part 15 STEP 15.6 -- Analytics maps + report-builder helpers (section L-V1/V2/V3, R2).

* GET /api/v1/ui/insights/candidate-heat -- where candidates live, AGGREGATED to city level.
  Free-text candidate locations are matched to a known city (or a 6-digit PIN code whose
  city is named in the same text). Exact addresses are never returned, and any city with
  fewer than MIN_CELL (5) candidates is folded into one "other places" count so no small
  group of people can be singled out on the map.
* GET /api/v1/ui/insights/jobs-by-location -- open (published) jobs per location, with map
  coordinates when the city is known (office coordinates first, then the city table).
* GET /api/v1/ui/insights/report-schedules -- the caller's scheduled report deliveries
  (read-only; creating one stays on /api/v1/intelligence/reports/{id}/schedules).

Tenant scoping: TenantOwned ORM read filter + an explicit tenant_id filter on every query.
No migrations -- read-only aggregates over existing tables.
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/insights", tags=["ui-insights"])

MIN_CELL = 5

# City centres only (never a street): India's metros + state capitals + common hiring cities.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "mumbai": (19.076, 72.8777), "delhi": (28.7041, 77.1025), "new delhi": (28.6139, 77.209),
    "bangalore": (12.9716, 77.5946), "bengaluru": (12.9716, 77.5946), "hyderabad": (17.385, 78.4867),
    "secunderabad": (17.4399, 78.4983), "chennai": (13.0827, 80.2707), "kolkata": (22.5726, 88.3639),
    "pune": (18.5204, 73.8567), "ahmedabad": (23.0225, 72.5714), "jaipur": (26.9124, 75.7873),
    "surat": (21.1702, 72.8311), "lucknow": (26.8467, 80.9462), "kanpur": (26.4499, 80.3319),
    "nagpur": (21.1458, 79.0882), "indore": (22.7196, 75.8577), "thane": (19.2183, 72.9781),
    "navi mumbai": (19.033, 73.0297), "bhopal": (23.2599, 77.4126), "visakhapatnam": (17.6868, 83.2185),
    "vizag": (17.6868, 83.2185), "vadodara": (22.3072, 73.1812), "patna": (25.5941, 85.1376),
    "ghaziabad": (28.6692, 77.4538), "ludhiana": (30.901, 75.8573), "agra": (27.1767, 78.0081),
    "nashik": (19.9975, 73.7898), "faridabad": (28.4089, 77.3178), "meerut": (28.9845, 77.7064),
    "rajkot": (22.3039, 70.8022), "varanasi": (25.3176, 82.9739), "srinagar": (34.0837, 74.7973),
    "amritsar": (31.634, 74.8723), "coimbatore": (11.0168, 76.9558), "madurai": (9.9252, 78.1198),
    "tiruchirappalli": (10.7905, 78.7047), "trichy": (10.7905, 78.7047), "salem": (11.6643, 78.146),
    "vellore": (12.9165, 79.1325), "kochi": (9.9312, 76.2673), "cochin": (9.9312, 76.2673),
    "thiruvananthapuram": (8.5241, 76.9366), "trivandrum": (8.5241, 76.9366), "guwahati": (26.1445, 91.7362),
    "chandigarh": (30.7333, 76.7794), "bhubaneswar": (20.2961, 85.8245), "raipur": (21.2514, 81.6296),
    "ranchi": (23.3441, 85.3096), "dehradun": (30.3165, 78.0322), "gurugram": (28.4595, 77.0266),
    "gurgaon": (28.4595, 77.0266), "noida": (28.5355, 77.391), "mysore": (12.2958, 76.6394),
    "mysuru": (12.2958, 76.6394), "kurnool": (15.8281, 78.0373), "vijayawada": (16.5062, 80.648),
    "tirupati": (13.6288, 79.4192), "warangal": (17.9689, 79.5941), "mangalore": (12.9141, 74.856),
    "mangaluru": (12.9141, 74.856), "hubli": (15.3647, 75.124), "jodhpur": (26.2389, 73.0243),
    "udaipur": (24.5854, 73.7125), "goa": (15.2993, 74.124), "panaji": (15.4909, 73.8278),
    "puducherry": (11.9416, 79.8083), "pondicherry": (11.9416, 79.8083),
}
# Friendly display name per alias (so "bengaluru" and "bangalore" land in ONE cell).
CANONICAL: dict[str, str] = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "cochin": "Kochi", "kochi": "Kochi", "trivandrum": "Thiruvananthapuram", "thiruvananthapuram": "Thiruvananthapuram",
    "mysore": "Mysuru", "mysuru": "Mysuru", "vizag": "Visakhapatnam", "visakhapatnam": "Visakhapatnam",
    "trichy": "Tiruchirappalli", "tiruchirappalli": "Tiruchirappalli", "mangalore": "Mangaluru", "mangaluru": "Mangaluru",
    "pondicherry": "Puducherry", "puducherry": "Puducherry",
}
# Longest names first so "new delhi" / "navi mumbai" win over "delhi" / "mumbai".
_CITY_NAMES = sorted(CITY_COORDS, key=len, reverse=True)
_CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in _CITY_NAMES) + r")\b")


def city_of(text: Optional[str]) -> Optional[str]:
    """The city a free-text location names, as a display name -- or None."""
    if not text:
        return None
    m = _CITY_RE.search(text.lower())
    if not m:
        return None
    key = m.group(1)
    return CANONICAL.get(key, key.title())


def _coords(display: str) -> Optional[tuple[float, float]]:
    return CITY_COORDS.get(display.lower())


def _num(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("/candidate-heat")
def candidate_heat(db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.application.view"))):
    from app.models.candidate import Candidate

    tenant = require_current_tenant()
    counts: dict[str, int] = {}
    unknown = 0
    for (location,) in db.query(Candidate.location).filter(Candidate.tenant_id == tenant.tenant_id):
        city = city_of(location)
        if city is None:
            unknown += 1
        else:
            counts[city] = counts.get(city, 0) + 1
    cells, hidden = [], 0
    for city, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n < MIN_CELL:
            hidden += n  # too few to show without singling people out
            continue
        lat, lng = _coords(city) or (None, None)
        cells.append({"city": city, "lat": lat, "lng": lng, "count": n})
    return {"cells": cells, "hidden_small": hidden, "unknown": unknown, "min_cell": MIN_CELL,
            "total": sum(counts.values()) + unknown}


@router.get("/jobs-by-location")
def jobs_by_location(db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.job.view"))):
    from app.models.core_hr import Location
    from app.models.job_role import JobRole

    tenant = require_current_tenant()
    offices = {}
    for loc in db.query(Location).filter(Location.tenant_id == tenant.tenant_id):
        lat, lng = _num(loc.geo_lat), _num(loc.geo_lng)
        if lat is not None and lng is not None and loc.name:
            offices[loc.name.strip().lower()] = (lat, lng)
    rows = (
        db.query(JobRole.location, func.count(JobRole.id))
        .filter(JobRole.tenant_id == tenant.tenant_id, JobRole.status == "published")
        .group_by(JobRole.location)
        .all()
    )
    out: dict[str, dict] = {}
    for location, n in rows:
        label = (location or "").strip() or None
        key = (label or "").lower()
        coords = offices.get(key)
        city = city_of(label)
        if coords is None and city:
            coords = _coords(city)
        name = label or ""
        entry = out.setdefault(name, {"location": label, "city": city, "lat": coords[0] if coords else None,
                                      "lng": coords[1] if coords else None, "count": 0})
        entry["count"] += n
    return {"locations": sorted(out.values(), key=lambda r: -r["count"]), "total": sum(r["count"] for r in out.values())}


@router.get("/report-schedules")
def report_schedules(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.view"))):
    from app.models.intelligence import ReportSchedule, SavedReport

    tenant = require_current_tenant()
    rows = (
        db.query(ReportSchedule, SavedReport)
        .join(SavedReport, SavedReport.id == ReportSchedule.report_id)
        .filter(ReportSchedule.tenant_id == tenant.tenant_id, SavedReport.owner_user_id == current_user.id)
        .all()
    )
    return [
        {"id": str(s.id), "report_id": str(r.id), "report_name": r.name, "frequency": s.frequency, "hour": s.hour,
         "day_of_week": s.day_of_week, "day_of_month": s.day_of_month, "recipients": list(s.recipients_json or []),
         "format": s.format, "enabled": bool(s.enabled),
         "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
         "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s, r in rows
    ]
