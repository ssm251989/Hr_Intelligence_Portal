"""platform/branding/api_router.py + platform/i18n/api_router.py over real HTTP, plus
platform/i18n/currency.py (Part 6 CHECKS)."""

from decimal import Decimal

import pytest

from app.platform.i18n.currency import RateNotFoundError, convert, format_amount, set_rate
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_me_bootstrap_over_http(client):
    response = client.get("/api/me/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["tenant"]["id"] == str(TENANT_1_ID)
    assert "primary_color" in body["branding"]
    assert isinstance(body["permissions"], list)


def test_public_branding_over_http_requires_no_auth(anonymous_client):
    response = anonymous_client.get("/api/v1/public/branding")
    assert response.status_code == 200
    assert "product_name" in response.json()


def test_public_i18n_bundle_over_http_requires_no_auth(anonymous_client):
    response = anonymous_client.get("/api/v1/public/i18n/en")
    assert response.status_code == 200
    assert response.json()["nav.jobs"] == "Jobs"


def test_i18n_override_crud_over_http(client):
    created = client.put("/api/v1/i18n/overrides", json={"locale": "en", "key": "nav.jobs", "value": "Openings"})
    assert created.status_code == 200
    override_id = created.json()["id"]

    listed = client.get("/api/v1/i18n/overrides", params={"locale": "en"})
    assert any(o["id"] == override_id for o in listed.json())

    bundle = client.get("/api/v1/public/i18n/en")
    assert bundle.json()["nav.jobs"] == "Openings"

    deleted = client.delete(f"/api/v1/i18n/overrides/{override_id}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/public/i18n/en").json()["nav.jobs"] == "Jobs"


def test_update_custom_css_over_http_sanitizes_before_storing(client):
    response = client.put("/api/v1/branding/custom-css", json={"custom_css": ".x { color: red; } </style><script>bad()</script>"})
    assert response.status_code == 200
    assert "</style>" not in response.json()["custom_css"]
    assert "<script" not in response.json()["custom_css"]

    # bootstrap only includes it once the branding.custom_css feature flag is on for this
    # tenant (off by default) -- proven off here, the flag-gating itself is this module's
    # own scope, not re-tested via HTTP.
    bootstrap = client.get("/api/me/bootstrap").json()
    assert bootstrap["branding"]["custom_css"] is None


# ---- currency ----


def test_convert_same_currency_is_a_no_op(db_session):
    assert convert(db_session, TENANT, Decimal("100"), "INR", "INR") == Decimal("100")


def test_convert_uses_the_latest_rate(db_session):
    set_rate(db_session, TENANT, from_currency="USD", to_currency="INR", rate=Decimal("83.0"))
    result = convert(db_session, TENANT, Decimal("10"), "USD", "INR")
    assert result == Decimal("830.0")


def test_convert_with_no_rate_on_file_raises(db_session):
    with pytest.raises(RateNotFoundError):
        convert(db_session, TENANT, Decimal("10"), "USD", "JPY")


def test_format_amount_uses_the_currency_symbol():
    assert format_amount(Decimal("1234.5"), "INR") == "₹1,234.50"
    assert format_amount(Decimal("10"), "XYZ") == "XYZ 10.00"
