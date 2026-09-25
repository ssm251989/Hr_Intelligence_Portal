"""GET /api/me/bootstrap (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 7) -- the single
payload the frontend is meant to build its whole runtime shell from: branding, locale/tz,
enabled modules, the caller's own permissions, feature flags, nav, and custom labels.

**Scoped down** (see docs/build_log.md's own Part 6 note): `nav` here is INFORMATIONAL --
every one of this app's existing pages is still real and reachable exactly as it is today
(the existing `require_roles()`/`ROLE_MATRIX` gate every one of them, unchanged). Rewiring
`AppLayout.tsx`'s sidebar to stop rendering anything not present in this response is a
separate, real frontend refactor (spec's own "the frontend must not render any menu/label
not returned here") not attempted in this pass -- what IS wired for real is `branding`
(replaces `frontend/src/bootstrap/defaults.ts` -- see the frontend section below) and
`permissions` (a real, live `authz.effective_permissions()` call, not a stub).
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.comms import BrandTheme
from app.models.user import User
from app.platform.branding.css_sanitizer import sanitize_css
from app.platform.iam.authz import effective_permissions
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.feature_flags import is_enabled as flag_enabled
from app.platform.tenancy.feature_flags import register_all as register_flags

# Mirrors AppLayout.tsx's own MODULES array -- informational only, see this module's own
# docstring on why nav enforcement itself isn't wired to this response yet.
_NAV_MODULES = (
    ("nav.overview", "/"), ("nav.jobs", "/jobs"), ("nav.candidates", "/candidates/dashboard"),
    ("nav.screening", "/screening/dashboard"), ("nav.shortlisting", "/shortlisting/dashboard"),
    ("nav.interviews", "/interviews/dashboard"), ("nav.hr_inbox", "/hr-inbox"), ("nav.approvals", "/approvals"),
    ("nav.salary", "/salary"), ("nav.bgv", "/bgv"), ("nav.offers", "/offers"),
    ("nav.reports", "/reports"), ("nav.settings", "/settings"),
)


def build_branding(db: Session, tenant: TenantContext) -> dict:
    theme = db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()
    settings_service = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    org_display_name = settings_service.get("org.display_name", ctx) or "HR Automation"

    custom_css = None
    cp_db = ControlPlaneSessionLocal()
    try:
        register_flags(cp_db)
        if theme and theme.custom_css and flag_enabled(cp_db, tenant.tenant_id, "branding.custom_css"):
            custom_css = sanitize_css(theme.custom_css)
    finally:
        cp_db.close()

    from app.platform.comms.theme import GENERIC_FALLBACK_THEME

    return {
        "product_name": org_display_name,
        "logo_file_id": str(theme.logo_file_id) if theme and theme.logo_file_id else None,
        "primary_color": (theme.primary_color if theme else None) or GENERIC_FALLBACK_THEME["primary_color"],
        "secondary_color": (theme.secondary_color if theme else None),
        "gradient_from": (theme.gradient_from if theme else None) or GENERIC_FALLBACK_THEME["gradient_from"],
        "gradient_to": (theme.gradient_to if theme else None) or GENERIC_FALLBACK_THEME["gradient_to"],
        "font_family": (theme.font_family if theme else None) or GENERIC_FALLBACK_THEME["font_family"],
        "support_contact": settings_service.get("org.support_email", ctx) or None,
        "legal_links": settings_service.get("org.legal_links", ctx) or [],
        "custom_css": custom_css,
    }


def build_bootstrap(db: Session, tenant: TenantContext, user: Optional[User], *, locale: Optional[str] = None) -> dict:
    from app.platform.i18n.service import DEFAULT_LOCALE, overrides_for

    settings_service = SettingsService(db)
    ctx = SettingContext(tenant=tenant, scope_ids={"user": user.id} if user is not None else {})
    resolved_locale = locale or settings_service.get("org.locale", ctx) or DEFAULT_LOCALE
    resolved_locale = resolved_locale.split("-")[0] if "-" in resolved_locale else resolved_locale

    permissions = sorted(effective_permissions(db, tenant, user)) if user is not None else []
    custom_labels = overrides_for(db, tenant, resolved_locale)

    cp_db = ControlPlaneSessionLocal()
    try:
        register_flags(cp_db)
        from app.platform.tenancy.models_cp import FeatureFlag

        feature_flags = {f.key: flag_enabled(cp_db, tenant.tenant_id, f.key) for f in cp_db.query(FeatureFlag.key).all()}
    finally:
        cp_db.close()

    return {
        "tenant": {"id": str(tenant.tenant_id), "slug": tenant.slug},
        "branding": build_branding(db, tenant),
        "locale": resolved_locale,
        "tz": settings_service.get("org.timezone", ctx) or "Asia/Kolkata",
        "permissions": permissions,
        "feature_flags": feature_flags,
        "nav": [{"label_key": key, "path": path} for key, path in _NAV_MODULES],
        "custom_labels": custom_labels,
        # Part 12: every AI affordance in the UI is gated on these (AI disabled -> hidden).
        "ai": _ai_flags(db, tenant),
    }


def _ai_flags(db: Session, tenant: TenantContext) -> dict:
    from app.platform.ai.governance import feature_flags

    return feature_flags(db, tenant)
