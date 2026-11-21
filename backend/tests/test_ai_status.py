"""H3 (Part 27): config health said "connect an AI provider" while AI worked (server key, no routed connection)."""

from app.experience import config_health
from app.platform.ai import status
from app.platform.tenancy.context import TENANT_1_ID, TenantContext


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def test_server_key_counts_as_configured_everywhere(db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(status, "_s", lambda db, t, k: {"ai.enabled": True, "ai.provider": "anthropic"}.get(k))
    monkeypatch.setattr("app.experience.ui_genai_router.company_key", lambda db, t: None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("app.platform.connectors.router.ConnectorRouter.try_resolve", lambda self, purpose: None)
    assert status.ai_status(db_session, _tenant()) == (True, None)
    issues = config_health.check(db_session, _tenant())
    items = issues["issues"] if isinstance(issues, dict) else issues
    assert not [i for i in items if (i.get("purpose") or "").startswith("llm.")]


def test_no_key_and_no_connection_is_not_configured(db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(status, "_s", lambda db, t, k: {"ai.enabled": True, "ai.provider": "anthropic"}.get(k))
    monkeypatch.setattr("app.experience.ui_genai_router.company_key", lambda db, t: None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("app.platform.connectors.router.ConnectorRouter.try_resolve", lambda self, purpose: None)
    ok, why = status.ai_status(db_session, _tenant())
    assert ok is False and "no AI key" in why
