"""Part 17.3: map data for every map (Home "People by office", Jobs / Analytics "Jobs by
location").

- GET /api/v1/geo/config                     tile URL + attribution + allowed-country box
- GET /api/v1/geo/places?kind=offices|jobs   placed points + "Location not found" list
- PUT /api/v1/geo/fix                        put one place on the map (city name or lat/lng)

Places are resolved by app/platform/geo/service.py (manual fix > office coordinates > cache >
built-in city table > geocoding connection). Anything still unknown is looked up online in
the background (never while the page waits) and shown under the map meanwhile.
Every query filters on the current company's tenant_id explicitly.
"""

from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform.geo import service as geo
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/geo", tags=["geo"])

_VIEW = {"offices": "core_hr.employee.view", "jobs": "recruitment.job.view"}
_FIX = {"offices": "core_hr.org.edit", "jobs": "recruitment.job.edit"}


def _need(db: Session, tenant, user: User, permission: str) -> None:
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


def _num(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("/config")
def geo_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.platform.geo.india_cities import INDIA_BOUNDS
    from app.platform.settings.resolver import SettingContext, SettingsService

    tenant = require_current_tenant()
    s, ctx = SettingsService(db), SettingContext(tenant=tenant)
    lat_min, lat_max, lng_min, lng_max = INDIA_BOUNDS
    countries = s.get("geo.countries", ctx) or ["IN"]
    return {"tile_url": s.get("geo.tile_url", ctx), "attribution": s.get("geo.tile_attribution", ctx),
            "countries": countries, "bounds": [[lat_min, lng_min], [lat_max, lng_max]] if countries == ["IN"] else None}


def _office_rows(db: Session, tenant) -> list[dict]:
    from app.models.core_hr import Employee, EmploymentRecord, Location

    counts = dict(
        db.query(EmploymentRecord.location_id, func.count(func.distinct(EmploymentRecord.employee_id)))
        .join(Employee, Employee.id == EmploymentRecord.employee_id)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_to.is_(None), Employee.status.in_(("active", "on_notice")))
        .group_by(EmploymentRecord.location_id).all()
    )
    rows = []
    for loc in db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name):
        n = counts.get(loc.id, 0)
        if not n:
            continue
        rows.append({"key": str(loc.id), "label": loc.name, "text": ", ".join(x for x in (loc.name, loc.state) if x),
                     "count": n, "lat": _num(loc.geo_lat), "lng": _num(loc.geo_lng), "link": f"/directory?location={loc.id}",
                     "fix": {"kind": "offices", "location_id": str(loc.id), "text": loc.name}})
    return rows


def _job_rows(db: Session, tenant) -> list[dict]:
    from app.models.job_role import JobRole

    rows = []
    q = (db.query(JobRole.location, func.count(JobRole.id))
         .filter(JobRole.tenant_id == tenant.tenant_id, JobRole.status == "published").group_by(JobRole.location))
    for location, n in q.all():
        label = (location or "").strip()
        rows.append({"key": label.lower() or "-", "label": label or None, "text": label, "count": n, "lat": None, "lng": None,
                     "link": f"/jobs?status=published{'&location=' + label if label else ''}",
                     "fix": {"kind": "jobs", "text": label}})
    return rows


@router.get("/places")
def places(kind: Literal["offices", "jobs"], background: BackgroundTasks, db: Session = Depends(get_db),
           current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, _VIEW[kind])
    countries = geo._countries(db, tenant)
    rows = _office_rows(db, tenant) if kind == "offices" else _job_rows(db, tenant)
    placed, not_found, pending = [], [], []
    for row in rows:
        lat, lng, source, where = row.pop("lat"), row.pop("lng"), None, None
        text = row.pop("text")
        if lat is not None and lng is not None:
            if geo.in_bounds(lat, lng, countries):
                source, where = "record", None
            else:
                lat = lng = None
                where = "outside"
        if lat is None:
            place, status = geo.resolve(db, tenant, text)
            if place is not None:
                lat, lng, source = place.lat, place.lng, place.source
            else:
                where = where or status
                if status == "pending":
                    pending.append(text)
        if lat is not None:
            placed.append({**row, "lat": lat, "lng": lng, "source": source})
        else:
            not_found.append({**row, "reason": "no_place" if where == "empty" else where})
    if pending and geo.online_allowed(db, tenant):
        background.add_task(geo.lookup_later, tenant.tenant_id, tenant.slug, tenant.isolation, pending)
    return {"kind": kind, "places": placed, "not_found": not_found, "looking_up": len(pending) if geo.online_allowed(db, tenant) else 0,
            "total": sum(r["count"] for r in rows)}


class FixIn(BaseModel):
    kind: Literal["offices", "jobs"]
    text: str = Field(min_length=1, max_length=255)  # the place text as shown in the list
    location_id: Optional[str] = None  # offices: also saved on the office record
    city: Optional[str] = Field(None, max_length=255)  # e.g. "Hyderabad" (looked up in the city table)
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.put("/fix")
def fix_place(payload: FixIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.audit.service import log_action

    tenant = require_current_tenant()
    _need(db, tenant, current_user, _FIX[payload.kind])
    if payload.lat is not None and payload.lng is not None:
        lat, lng, label = payload.lat, payload.lng, payload.city or payload.text
    elif payload.city:
        hit = geo.offline(payload.city)
        if hit is None:
            cached, _status = geo.resolve(db, tenant, payload.city)
            hit = cached
        if hit is None:
            raise HTTPException(status_code=400, detail="We don't know that city yet. Type a bigger city nearby, or enter the map point (latitude, longitude).")
        lat, lng, label = hit.lat, hit.lng, hit.label
    else:
        raise HTTPException(status_code=400, detail="Give a city name, or a latitude and longitude.")
    try:
        place = geo.set_manual(db, tenant, payload.text, lat=lat, lng=lng, label=label, actor=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.kind == "offices" and payload.location_id:
        from app.models.core_hr import Location

        loc = db.query(Location).filter(Location.tenant_id == tenant.tenant_id, Location.id == payload.location_id).first()
        if loc is None:
            raise HTTPException(status_code=404, detail="Office not found")
        loc.geo_lat, loc.geo_lng = f"{lat:.5f}", f"{lng:.5f}"
        db.commit()
    import uuid as _uuid

    log_action(db, "geo_place", _uuid.UUID(payload.location_id) if payload.location_id else None, "place_fixed", current_user.email,
               {"kind": payload.kind, "text": payload.text, "lat": lat, "lng": lng})
    return {"text": payload.text, "lat": place.lat, "lng": place.lng, "label": place.label, "source": place.source}
