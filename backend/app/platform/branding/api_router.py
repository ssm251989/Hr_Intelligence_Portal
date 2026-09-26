"""Bootstrap + public branding endpoints (docs/HRMS_COMPLETE_SPEC.txt Part 6 sections 5
+ 7)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.core.database import get_db
from app.models.comms import BrandTheme
from app.models.user import User
from app.platform.branding.bootstrap import build_bootstrap
from app.platform.branding.css_sanitizer import CustomCssTooLargeError, sanitize_css
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(tags=["branding"])
public_router = APIRouter(prefix="/api/v1/public", tags=["branding-public"])


@router.get("/api/me/bootstrap")
def me_bootstrap(locale: Optional[str] = None, db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_current_user_optional)):
    tenant = require_current_tenant()
    return build_bootstrap(db, tenant, current_user, locale=locale)


@public_router.get("/branding")
def public_branding(host: Optional[str] = None, db: Session = Depends(get_db)):
    """Pre-login theming (a login page needs branding before anyone's authenticated).
    Under TENANCY_MODE=single there's exactly one tenant regardless of `host` -- this
    still resolves through TenantResolverMiddleware the same as every other request, so
    `host` here is accepted for API-shape parity with a future multi-tenant deployment
    but doesn't itself change which tenant answers."""
    tenant = require_current_tenant()
    from app.platform.branding.bootstrap import build_branding

    return build_branding(db, tenant)


class CustomCssUpdate(BaseModel):
    custom_css: str


@router.put("/api/v1/branding/custom-css")
def update_custom_css(payload: CustomCssUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    theme = db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()
    if theme is None:
        theme = BrandTheme(tenant_id=tenant.tenant_id, name="Default", is_default=True)
        db.add(theme)
    try:
        theme.custom_css = sanitize_css(payload.custom_css)
    except CustomCssTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {"custom_css": theme.custom_css}


# Part 15 app shell (L-H5): the bell groups the signed-in user's in-app notifications by
# module. In-app messages are ordinary outbound_messages rows (channel "in_app") addressed
# to the user's email or id; the module is inferred from the entity/purpose they carry.
_NOTIFICATION_MODULES = (
    ("hiring", ("job", "candidate", "application", "interview", "offer", "bgv", "salary", "screening", "shortlist", "inbox")),
    ("onboarding", ("onboard", "preboard", "joiner")),
    ("people", ("employee", "profile", "org")),
    ("performance", ("performance", "goal", "review", "checkin", "compensation", "succession")),
    ("helpdesk", ("ticket", "helpdesk", "service_desk")),
    ("assets", ("asset", "allocation")),
    ("exits", ("separation", "resignation", "clearance", "exit")),
    ("approvals", ("approval", "workflow")),
)


def _notification_module(entity_type: Optional[str], purpose: Optional[str]) -> str:
    haystack = f"{entity_type or ''} {purpose or ''}".lower()
    for module, words in _NOTIFICATION_MODULES:
        if any(w in haystack for w in words):
            return module
    return "general"


@router.get("/api/me/notifications")
def my_notifications(limit: int = 30, db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_current_user_optional)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Please sign in again.")
    from app.models.comms import OutboundMessage

    tenant = require_current_tenant()
    addresses = [a for a in (current_user.email, str(current_user.id)) if a]
    rows = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.channel == "in_app", OutboundMessage.to_addresses.overlap(addresses))
        .order_by(OutboundMessage.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    groups: dict[str, list[dict]] = {}
    for m in rows:
        groups.setdefault(_notification_module(m.related_entity_type, m.purpose), []).append({
            "id": str(m.id),
            "title": m.subject or "Update",
            "entity_type": m.related_entity_type,
            "entity_id": str(m.related_entity_id) if m.related_entity_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return {"groups": [{"module": k, "items": v} for k, v in groups.items()], "total": len(rows)}
