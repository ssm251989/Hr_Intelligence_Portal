"""Part 16.3 -- helpers for the reorganised Settings.

- `GET /api/v1/settings/usage` -- Billing & licence page: what counts towards the plan
  (active employees, active users, modules switched on). Read-only; the licence itself lives
  in the central Platform Console (K-M3), so this only reports what this installation sees.
- `POST /api/v1/settings/two-step/invite` -- "Invite them to set it up": sends an in-app reminder (shown in
  the bell) to everyone without 2-step verification, linking to the setup page.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/settings", tags=["settings-home"])


@router.get("/usage")
def usage(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    from app.models.core_hr import Employee
    from app.platform.modules import enabled_modules

    tenant = require_current_tenant()
    employees = db.query(func.count(Employee.id)).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice"))).scalar() or 0
    users = db.query(func.count(User.id)).filter(User.tenant_id == tenant.tenant_id).scalar() or 0
    plan = None
    try:
        from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
        from app.platform.tenancy.models_cp import Plan, Tenant

        cp = ControlPlaneSessionLocal()
        try:
            row = cp.get(Tenant, tenant.tenant_id)
            if row is not None and row.plan_id:
                p = cp.get(Plan, row.plan_id)
                plan = getattr(p, "name", None) or getattr(p, "code", None)
        finally:
            cp.close()
    except Exception:  # control plane unreachable -> the page just shows no plan name
        plan = None
    return {"active_employees": employees, "users": users, "modules": sorted(enabled_modules(db, tenant)), "plan": plan}


@router.post("/two-step/invite")
def invite_two_step(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    """Send each user without 2-step verification an in-app reminder with the link to set it up."""
    tenant = require_current_tenant()
    people = [u for u in db.query(User).filter(User.tenant_id == tenant.tenant_id).all() if not u.mfa_totp_enrolled_at and not u.mfa_email_otp_enabled]
    from app.models.comms import OutboundMessage

    for u in people:
        # In-app messages are outbound_messages rows on the "in_app" channel (the bell reads them).
        db.add(OutboundMessage(
            tenant_id=tenant.tenant_id, channel="in_app", purpose="system.security", to_addresses=[u.email],
            subject="Please set up 2-step verification - it keeps your account safe (Settings > People & access).",
            body_ref="/settings/people/two-step", status="sent", related_entity_type="security",
        ))
    db.commit()
    sent = len(people)
    return {"people": len(people), "reminded": sent}
