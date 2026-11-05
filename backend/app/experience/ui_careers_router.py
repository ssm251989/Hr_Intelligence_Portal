"""Part 15.4 careers portal (docs/HRMS_COMPLETE_SPEC.txt L A4-A7, K B1): small public,
read-only extras the restyled career site shows beside the existing /public/jobs API.

- GET /api/v1/public/careers/site -- the company's own careers intro, benefits and FAQ
  (A6, "editable per client"). Read from the settings keys below ONLY when they are
  registered; until a later step registers them (with help text) every section is empty
  and the site simply renders nothing for it -- never built-in wording.
- GET /api/v1/public/careers/jobs/{job_id}/extras -- the published job's own benefits
  text, job type and application deadline (data the company already publishes).

Candidate status tracking (A7) is NOT served here: applications carry no unguessable
candidate-facing token today, and the application id alone is also used in staff URLs,
so it is not a safe bearer credential. That needs a token column (migration) first.

Both endpoints are tenant-scoped (require_current_tenant) and expose no personal data.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.service import close_job_if_deadline_passed, get_application_deadline
from app.models.job_role import JobRole
from app.platform.settings.registry import is_registered
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/public/careers", tags=["careers-public"])

INTRO_KEY = "careers.site.intro"
BENEFITS_KEY = "careers.site.benefits"  # json: [{"title": str, "body": str, "emoji"?: str}]
FAQ_KEY = "careers.site.faq"  # json: [{"question": str, "answer": str}]

_MAX_ITEMS = 30
_MAX_TEXT = 2000


def _text(value: Any) -> str:
    return str(value).strip()[:_MAX_TEXT] if isinstance(value, (str, int, float)) else ""


def _setting(service: SettingsService, ctx: SettingContext, key: str) -> Any:
    if not is_registered(key):
        return None
    try:
        return service.get(key, ctx)
    except Exception:  # a bad stored value must never take the public site down
        return None


def _benefits(raw: Any) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("title")):
            out.append({"title": _text(item.get("title")), "body": _text(item.get("body")), "emoji": _text(item.get("emoji")) or None})
    return out[:_MAX_ITEMS]


def _faq(raw: Any) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("question")) and _text(item.get("answer")):
            out.append({"question": _text(item.get("question")), "answer": _text(item.get("answer"))})
    return out[:_MAX_ITEMS]


@router.get("/site")
def careers_site(db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    service = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    intro = _setting(service, ctx, INTRO_KEY)
    return {
        "intro": _text(intro) or None,
        "benefits": _benefits(_setting(service, ctx, BENEFITS_KEY)),
        "faq": _faq(_setting(service, ctx, FAQ_KEY)),
    }


@router.get("/jobs/{job_id}/extras")
def careers_job_extras(job_id: uuid.UUID, db: Session = Depends(get_db)):
    require_current_tenant()
    job = db.get(JobRole, job_id)
    if job:
        close_job_if_deadline_passed(db, job)
    if not job or job.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")
    deadline = get_application_deadline(job)
    return {
        "job_type": job.job_type or None,
        "benefits": (job.benefits or "").strip() or None,
        "application_deadline": deadline.isoformat() if deadline else None,
    }
