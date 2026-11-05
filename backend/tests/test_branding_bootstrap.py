"""platform/branding/bootstrap.py + api_router.py -- /api/me/bootstrap, public branding,
custom CSS sanitization (Part 6 CHECKS: "two test tenants with different logos/colours/
labels render different UIs from the same build" -- exercised here as "the SAME build
returns DIFFERENT bootstrap payloads once tenant #1's own brand_theme/org.display_name/
i18n_overrides are changed", the single-tenant-deployment form of that same proof)."""

from app.models.comms import BrandTheme
from app.platform.branding.bootstrap import build_bootstrap
from app.platform.branding.css_sanitizer import sanitize_css
from app.platform.i18n.service import set_override
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_bootstrap_returns_the_real_tenant_1_brand_theme(db_session):
    payload = build_bootstrap(db_session, TENANT, None)
    assert payload["tenant"]["id"] == str(TENANT_1_ID)
    assert payload["branding"]["primary_color"]  # a real value, not None (tenant #1 has a real brand_themes row)


def test_bootstrap_reflects_a_changed_org_display_name(db_session):
    SettingsService(db_session).set("org.display_name", "Totally Different Co", scope_type="tenant", scope_id=None, actor="test", tenant=TENANT)
    payload = build_bootstrap(db_session, TENANT, None)
    assert payload["branding"]["product_name"] == "Totally Different Co"


def test_bootstrap_reflects_changed_brand_colors(db_session):
    theme = db_session.query(BrandTheme).filter(BrandTheme.tenant_id == TENANT_1_ID, BrandTheme.is_default.is_(True)).first()
    original = theme.primary_color
    theme.primary_color = "#ff00ff"
    db_session.commit()

    payload = build_bootstrap(db_session, TENANT, None)
    assert payload["branding"]["primary_color"] == "#ff00ff"
    assert payload["branding"]["primary_color"] != original


def test_bootstrap_permissions_are_empty_for_an_anonymous_caller(db_session):
    payload = build_bootstrap(db_session, TENANT, None)
    assert payload["permissions"] == []


def test_bootstrap_permissions_reflect_a_real_logged_in_user(db_session):
    import uuid

    from app.core.security import hash_password
    from app.models.user import User
    from app.platform.iam.roles import bridge_single_user

    user = User(email=f"bootstrap-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="admin")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    bridge_single_user(db_session, TENANT, user)

    payload = build_bootstrap(db_session, TENANT, user)
    assert "iam.roles.configure" in payload["permissions"]


def test_bootstrap_custom_labels_reflect_i18n_overrides(db_session):
    set_override(db_session, TENANT, "en", "entity.employee", "Associate")
    payload = build_bootstrap(db_session, TENANT, None, locale="en")
    assert payload["custom_labels"]["entity.employee"] == "Associate"


def test_bootstrap_locale_prefers_a_per_user_override(db_session):
    import uuid

    from app.core.security import hash_password
    from app.models.user import User

    user = User(email=f"locale-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    SettingsService(db_session).set("org.locale", "hi-IN", scope_type="user", scope_id=user.id, actor="test", tenant=TENANT)
    payload = build_bootstrap(db_session, TENANT, user)
    assert payload["locale"] == "hi"

    # a different user (no override) still gets the tenant-wide default
    other_payload = build_bootstrap(db_session, TENANT, None)
    assert other_payload["locale"] != "hi"


# ---- custom CSS sanitizer ----


def test_sanitize_css_strips_style_tag_breakout():
    cleaned = sanitize_css("body { color: red; } </style><script>alert(1)</script>")
    assert "</style>" not in cleaned
    assert "<script" not in cleaned


def test_sanitize_css_strips_import_and_expression():
    cleaned = sanitize_css("@import url(evil.css); .x { width: expression(alert(1)); }")
    assert "@import" not in cleaned
    assert "expression(" not in cleaned


def test_sanitize_css_strips_javascript_url():
    cleaned = sanitize_css(".x { background: url(javascript:alert(1)); }")
    assert "javascript:" not in cleaned


def test_sanitize_css_leaves_ordinary_css_untouched():
    ordinary = ".btn { background-color: #2563eb; padding: 8px 16px; border-radius: 4px; }"
    assert sanitize_css(ordinary) == ordinary


def test_sanitize_css_rejects_oversized_input():
    import pytest

    from app.platform.branding.css_sanitizer import CustomCssTooLargeError, MAX_CUSTOM_CSS_LENGTH

    with pytest.raises(CustomCssTooLargeError):
        sanitize_css("a" * (MAX_CUSTOM_CSS_LENGTH + 1))
