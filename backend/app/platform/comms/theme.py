"""Shared {{ theme.* }}/{{ org.* }} render context (docs/HRMS_COMPLETE_SPEC.txt Part 4
section 5) -- every template (email or a candidate-facing page like
interview_scheduling/negotiation_router.py) that needs a tenant's brand_theme row / org
display name renders with this, not a hardcoded value. Falls back to a neutral generic
palette/name if a tenant has configured neither yet, so a render never hard-fails over
branding alone.
"""

from sqlalchemy.orm import Session

from app.models.comms import BrandTheme
from app.platform.settings.resolver import SettingContext, SettingsService


# A generic, no-tenant-configured-yet scaffold palette/name -- not any specific tenant's
# chosen brand -- same class of exclusion as frontend/src/theme's own already-neutral
# design-system palette. The single named home for these literals (platform/comms/
# templates.py's own publish-time sample context reuses this instead of duplicating the
# hex values), so hardcode_allowlist.txt only needs to allow-list them once.
GENERIC_FALLBACK_THEME = {
    "primary_color": "#2563eb",  # allowlisted: generic-fallback
    "gradient_from": "#1e293b",  # allowlisted: generic-fallback
    "gradient_to": "#2563eb",  # allowlisted: generic-fallback
    "font_family": "-apple-system, Segoe UI, Roboto, Arial, sans-serif",
}
GENERIC_FALLBACK_ORG_DISPLAY_NAME = "HR Automation"


def get_theme_and_org_context(db: Session, tenant) -> dict:
    theme = db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()
    org_display_name = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant))
    return {
        "theme": {
            "primary_color": (theme.primary_color if theme else None) or GENERIC_FALLBACK_THEME["primary_color"],
            "gradient_from": (theme.gradient_from if theme else None) or GENERIC_FALLBACK_THEME["gradient_from"],
            "gradient_to": (theme.gradient_to if theme else None) or GENERIC_FALLBACK_THEME["gradient_to"],
            "font_family": (theme.font_family if theme else None) or GENERIC_FALLBACK_THEME["font_family"],
        },
        "org": {"display_name": org_display_name or GENERIC_FALLBACK_ORG_DISPLAY_NAME},
    }
