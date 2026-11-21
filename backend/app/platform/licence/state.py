"""Part 32: where a company stands with CTD Techs - and which modules CTD signed for.

  approved  a CTD-signed approval for THIS install id and company is in (access, or a later module change)
  grace     a company that already existed when Part 32 arrived and has no signed approval yet: works as before for
            14 days with the banner "Ask CTD Techs for your approval code" (so no one is cut off by surprise)
  locked    nothing signed (a new install / sign-up waiting for CTD, or the grace is over): only sign-in, the waiting
            page and the code entry open

Database rows are never trusted on their own: every stored approval is re-verified with CTD's public key (cached for
60 s, so "re-checked at start and every hour" holds with room to spare), and a module counts as active only when the
newest valid approval lists it. valid_until (yearly licences): banner from 30 days before; afterwards the modules are
read-only (looked at, nothing new), never deleted.
"""

import logging
import math
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.platform.licence import codes

log = logging.getLogger(__name__)

GRACE_DAYS = 14
WARN_DAYS = 30
_cache: dict = {}
_ENFORCED = True  # tests switch this off for suites that are not about the licence (tests/conftest.py)


def enforced() -> bool:
    return _ENFORCED


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cp():
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal

    return ControlPlaneSessionLocal()


def _config_value(cp, key: str):
    from app.platform.tenancy.models_cp import PlatformConfig

    row = cp.get(PlatformConfig, key)
    return row.value_json if row is not None else None


def install_id(cp=None) -> str:
    """This installation's id (made once; an approval is valid for this install only)."""
    from app.platform.tenancy.models_cp import PlatformConfig

    own = cp is None
    cp = cp or _cp()
    try:
        value = _config_value(cp, "licence.install_id")
        if value and value.get("id"):
            return value["id"]
        new = str(uuid.uuid4())
        cp.add(PlatformConfig(key="licence.install_id", value_json={"id": new}, updated_by="licence"))
        cp.commit()
        return new
    finally:
        if own:
            cp.close()


def _valid_until(payload: dict) -> Optional[date]:
    raw = payload.get("valid_until")
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def check_payload(payload: dict, tenant, *, iid: str) -> None:
    """The approval is for this install and company (signature already checked)."""
    if payload.get("install_id") != iid:
        raise codes.CodeError("This code is for another installation.", "other_install")
    if payload.get("slug") != tenant.slug:
        raise codes.CodeError("This code is for another company.", "other_company")
    if payload.get("kind") not in ("access", "modules"):
        raise codes.CodeError("This is not an approval code.", "bad_kind")


def _approvals(tenant) -> list[dict]:
    """Every stored approval of this company whose CTD signature (and install / company) still checks out, newest first."""
    from app.platform.tenancy.models_cp import LicenceApproval

    cp = _cp()
    try:
        iid = install_id(cp)
        rows = (cp.query(LicenceApproval).filter(LicenceApproval.tenant_id == tenant.tenant_id)
                .order_by(LicenceApproval.created_at.desc()).limit(50).all())
        out = []
        for row in rows:
            try:
                payload = codes.decode_approval(row.code)
                check_payload(payload, tenant, iid=iid)
            except codes.CodeError as exc:
                _tamper(tenant, f"stored approval {row.id} refused: {exc.code}")
                continue
            out.append(payload)
        return sorted(out, key=lambda p: str(p.get("issued_at") or ""), reverse=True)
    finally:
        cp.close()


def _in_grace(tenant) -> Optional[int]:
    """Days left of the upgrade grace for a company that existed when Part 32 arrived, else None."""
    cp = _cp()
    try:
        grace = _config_value(cp, "licence.grace") or {}
    finally:
        cp.close()
    if str(tenant.tenant_id) not in (grace.get("tenants") or []):
        return None
    try:
        started = datetime.fromisoformat(grace["started_at"])
    except (KeyError, ValueError):
        return None
    remaining = (started + timedelta(days=GRACE_DAYS) - _now()).total_seconds()
    return math.ceil(remaining / 86400) if remaining > 0 else None


def standing(tenant) -> dict:
    """{"state": approved|grace|locked, "modules": [...] (signed), "valid_until", "expiring_in_days", "expired", "grace_days_left"}."""
    key = str(tenant.tenant_id)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    approvals = _approvals(tenant)
    if approvals:
        newest = approvals[0]
        until = _valid_until(newest)
        today = _now().date()
        out = {"state": "approved", "modules": sorted(newest.get("modules") or []), "valid_until": until.isoformat() if until else None,
               "expired": bool(until and today > until), "expiring_in_days": (until - today).days if until and 0 <= (until - today).days <= WARN_DAYS else None,
               "grace_days_left": None}
    else:
        days = _in_grace(tenant)
        out = {"state": "grace" if days else "locked", "modules": [], "valid_until": None, "expired": False, "expiring_in_days": None,
               "grace_days_left": days}
    _cache[key] = (time.monotonic() + 60, out)
    return out


def invalidate(tenant_id=None) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(str(tenant_id), None)


def locked(tenant) -> bool:
    return enforced() and standing(tenant)["state"] == "locked"


def allowed_modules(tenant) -> Optional[set[str]]:
    """The modules CTD signed for; None = no limit from the licence (grace, or not enforced)."""
    if not enforced():
        return None
    s = standing(tenant)
    if s["state"] == "grace":
        return None
    return set(s["modules"]) if s["state"] == "approved" else set()


def read_only(tenant) -> bool:
    """valid_until has passed: data can be looked at, nothing new is done."""
    return enforced() and standing(tenant)["expired"]


_told: set = set()


def _tamper(tenant, what: str) -> None:
    """Logged once per process for each finding (a row saying "active" without a signature, a bad stored code)."""
    mark = (str(tenant.tenant_id), what)
    if mark in _told:
        return
    _told.add(mark)
    log.warning("licence tamper check (%s): %s", getattr(tenant, "slug", tenant.tenant_id), what)


def tamper(tenant, what: str) -> None:
    _tamper(tenant, what)
