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
    # Part 15 A: the platform's default "Fresh" theme (brand green -> sky gradient).
    "primary_color": "#0E7C66",  # allowlisted: generic-fallback
    "gradient_from": "#0E7C66",  # allowlisted: generic-fallback
    "gradient_to": "#2F6FDE",  # allowlisted: generic-fallback
    "font_family": "Plus Jakarta Sans, system-ui, -apple-system, Segoe UI, Arial, sans-serif",
}
GENERIC_FALLBACK_ORG_DISPLAY_NAME = "HR Automation"


def get_theme_and_org_context(db: Session, tenant) -> dict:
    theme = db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()
    org_display_name = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant))
    return {
        # Part 17.11: {{ theme.logo_url }} -- absolute, so it works inside emails and letters
        "theme": {
            "primary_color": (theme.primary_color if theme else None) or GENERIC_FALLBACK_THEME["primary_color"],
            "gradient_from": (theme.gradient_from if theme else None) or GENERIC_FALLBACK_THEME["gradient_from"],
            "gradient_to": (theme.gradient_to if theme else None) or GENERIC_FALLBACK_THEME["gradient_to"],
            "font_family": (theme.font_family if theme else None) or GENERIC_FALLBACK_THEME["font_family"],
            "logo_url": logo_url(db, tenant),
        },
        "org": {"display_name": org_display_name or GENERIC_FALLBACK_ORG_DISPLAY_NAME},
    }


def logo_url(db: Session, tenant) -> str:
    """Absolute URL of the company logo ("" when none is uploaded)."""
    from app.core.config import settings as app_settings
    from app.models.experience import TenantMedia

    logo = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == "brand.logo").first()
    if logo is None or logo.updated_at is None:
        return ""
    from app.platform.links import public_base_url

    return f"{public_base_url()}/api/v1/public/media/brand.logo?v={int(logo.updated_at.timestamp())}"


def wrap_email_html(db: Session, tenant, body_html: str) -> str:
    """Part 17.11: every outgoing email gets the company header -- the logo when one is
    uploaded, else the company name -- above its own body."""
    import html as _html

    if not body_html:
        return body_html
    ctx = get_theme_and_org_context(db, tenant)
    name = _html.escape(ctx["org"]["display_name"] or "")
    colour = _html.escape(ctx["theme"]["primary_color"] or "#0E7C66")
    brand = (f'<img src="{_html.escape(ctx["theme"]["logo_url"], quote=True)}" alt="{name}" style="max-height:48px;max-width:220px;border:0">'
             if ctx["theme"]["logo_url"] else f'<span style="font:700 18px Arial,sans-serif;color:{colour}">{name}</span>')
    return ('<div style="max-width:640px;margin:0 auto;font-family:Arial,sans-serif">'
            f'<div style="padding:16px 0;border-bottom:3px solid {colour};margin-bottom:16px">{brand}</div>'
            f"{body_html}</div>")
