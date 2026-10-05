"""platform/ai/gateway.py's complete() -- purpose -> connection -> model; usage metered
(Part 3 CHECKS). Fakes the anthropic SDK's Anthropic client, same "fake the client class,
not the app's own function" convention as test_smtp_imap_adapter.py."""

import json

import pytest

from app.models.connection import Connection, ConnectionRoute
from app.models.secret import Secret, SecretScope
from app.platform.ai import gateway
from app.platform.connectors.purposes import register_purpose
from app.platform.connectors.router import NoConnectionForPurposeError
from app.platform.secrets.store import get_secret_store
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

register_settings_definitions()

TEST_LLM_PURPOSE = "test.llm.purpose"
register_purpose(TEST_LLM_PURPOSE)


class _FakeAnthropicResponse:
    def model_dump(self):
        return {"content": [{"type": "text", "text": "fake completion"}], "usage": {"input_tokens": 10, "output_tokens": 5}}


class _FakeMessages:
    calls: list = []

    def create(self, **kwargs):
        _FakeMessages.calls.append(kwargs)
        return _FakeAnthropicResponse()


class _FakeAnthropicClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.messages = _FakeMessages()


def _tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _make_anthropic_connection(db_session, actor="admin@example.com"):
    store = get_secret_store(db_session, Secret, SecretScope, str(TENANT_1_ID))
    secret_ref = "test-anthropic-secret"
    try:
        store.get(secret_ref)
    except Exception:
        store.put(secret_ref, json.dumps({"api_key": "sk-fake-key"}), created_by=actor)

    conn = Connection(tenant_id=TENANT_1_ID, name="Test Anthropic", provider_code="anthropic", capability=["LlmProvider"], config_json={}, secret_ref=secret_ref, status="active")
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    db_session.add(ConnectionRoute(tenant_id=TENANT_1_ID, purpose=TEST_LLM_PURPOSE, connection_id=conn.id, priority=1, enabled=True))
    db_session.commit()
    return conn


def test_complete_resolves_purpose_to_connection_and_calls_its_model(db_session, monkeypatch):
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _FakeMessages.calls.clear()
    _make_anthropic_connection(db_session)

    result = gateway.complete(
        db_session, _tenant_ctx(), purpose=TEST_LLM_PURPOSE, system="You are a test.",
        messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5",
    )

    assert result["content"][0]["text"] == "fake completion"
    assert _FakeMessages.calls[0]["model"] == "claude-haiku-4-5"


def test_complete_falls_back_to_the_settings_registry_model_when_none_given(db_session, monkeypatch):
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _FakeMessages.calls.clear()
    _make_anthropic_connection(db_session)

    # No `model` kwarg -- gateway.complete must resolve one from ai.models.* via
    # SettingsService rather than requiring every caller to know/pass it.
    gateway.complete(db_session, _tenant_ctx(), purpose=TEST_LLM_PURPOSE, system="sys", messages=[{"role": "user", "content": "hi"}])

    assert _FakeMessages.calls[0]["model"]  # some real model id string was resolved and used


def test_complete_raises_no_connection_for_purpose_when_unrouted(db_session):
    with pytest.raises(NoConnectionForPurposeError):
        gateway.complete(db_session, _tenant_ctx(), purpose="test.llm.totally_unrouted_purpose", system="sys", messages=[])


def test_usage_is_returned_for_metering(db_session, monkeypatch):
    """Part 3 section 1's own "usage metered per tenant" -- the token counts anthropic's
    own response carries must survive gateway.complete()'s return value for a caller
    (Part 12's usage_budget) to actually meter against, not be stripped out."""
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _make_anthropic_connection(db_session)

    result = gateway.complete(db_session, _tenant_ctx(), purpose=TEST_LLM_PURPOSE, system="sys", messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5")

    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["output_tokens"] == 5


def test_complete_always_sends_max_tokens(db_session, monkeypatch):
    """Fix 2026-10-05: governed calls (HR assistant, agents, triage) never passed max_tokens, which
    the provider requires -- every HR-assistant answer failed with TypeError."""
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _FakeMessages.calls.clear()
    _make_anthropic_connection(db_session)
    gateway.complete(db_session, _tenant_ctx(), purpose=TEST_LLM_PURPOSE, system="sys", messages=[{"role": "user", "content": "hi"}], _record=False)
    assert _FakeMessages.calls[-1]["max_tokens"] == 4096
    gateway.complete(db_session, _tenant_ctx(), purpose=TEST_LLM_PURPOSE, system="sys", messages=[{"role": "user", "content": "hi"}], max_tokens=300, _record=False)
    assert _FakeMessages.calls[-1]["max_tokens"] == 300
