"""Onboarding dashboard (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 5): upcoming joiners
with readiness %, overdue tasks by owner, BGV status, documents pending verification, and
offer-to-join drop-off."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.onboarding import BgvCase, PreboardingCase, PreboardingDocument
from app.onboarding import plans
from app.onboarding.portal import PreboardingPortal
from app.platform.tenancy.context import TenantContext


def summary(db: Session, tenant: TenantContext, *, horizon_days: int = 30, today: Optional[date] = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    portal = PreboardingPortal(db, tenant)
    cases = db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id).all()

    upcoming = sorted(
        (c for c in cases if c.status in ("invited", "in_progress", "ready") and today <= c.joining_date <= today + timedelta(days=horizon_days)),
        key=lambda c: c.joining_date,
    )
    overdue = plans.overdue_tasks(db, tenant, today=today)
    bgv = Counter(c.status for c in db.query(BgvCase).filter(BgvCase.tenant_id == tenant.tenant_id).all())
    docs_pending = (
        db.query(PreboardingDocument)
        .filter(PreboardingDocument.tenant_id == tenant.tenant_id, PreboardingDocument.verification_status == "pending")
        .count()
    )
    by_status = Counter(c.status for c in cases)
    closed = by_status["joined"] + by_status["no_show"] + by_status["revoked"]

    return {
        "upcoming_joiners": [
            {"case_id": str(c.id), "email": c.email, "joining_date": c.joining_date.isoformat(), "status": c.status,
             "readiness_percent": portal.readiness(c)["percent"]}
            for c in upcoming
        ],
        "overdue_tasks_by_owner": dict(Counter(t.owner_role for t in overdue)),
        "bgv_status": dict(bgv),
        "documents_pending_verification": docs_pending,
        "cases_by_status": dict(by_status),
        "offer_to_join_drop_off_percent": round(100 * (by_status["no_show"] + by_status["revoked"]) / closed) if closed else 0,
    }
