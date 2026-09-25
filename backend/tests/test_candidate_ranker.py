"""app/ai_services/candidate_ranker.py (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 4) --
the one ai_services call site migrated onto ai.gateway.complete() + the prompt registry.
Fakes the anthropic SDK's client, same convention as test_llm_gateway_routing.py."""

import json

from app.ai_services.candidate_ranker import CandidateRankingError, PROMPT_KEY, rank_candidate
from app.models.connection import Connection, ConnectionRoute
from app.models.secret import Secret, SecretScope
from app.platform.secrets.store import get_secret_store
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.recruitment import prompt_registry

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")

_FAKE_TOOL_INPUT = {
    "composite_score": 82, "rank_rationale": "Strong backend fundamentals, missing Kubernetes -- recommend.",
    "strengths": ["Python", "FastAPI"], "concerns": ["No Kubernetes experience"], "recommendation": "recommend",
}


class _FakeAnthropicResponse:
    def model_dump(self):
        return {
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "submit_candidate_ranking", "input": _FAKE_TOOL_INPUT}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


class _FakeMessages:
    calls: list = []

    def create(self, **kwargs):
        _FakeMessages.calls.append(kwargs)
        return _FakeAnthropicResponse()


class _FakeAnthropicClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.messages = _FakeMessages()


def _make_anthropic_connection(db_session, purpose="llm.judgment"):
    store = get_secret_store(db_session, Secret, SecretScope, str(TENANT_1_ID))
    secret_ref = "test-candidate-ranker-secret"
    try:
        store.get(secret_ref)
    except Exception:
        store.put(secret_ref, json.dumps({"api_key": "sk-fake-key"}), created_by="test")

    conn = Connection(tenant_id=TENANT_1_ID, name="Test Anthropic", provider_code="anthropic", capability=["LlmProvider"], config_json={}, secret_ref=secret_ref, status="active")
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    db_session.add(ConnectionRoute(tenant_id=TENANT_1_ID, purpose=purpose, connection_id=conn.id, priority=1, enabled=True))
    db_session.commit()
    return conn


def test_rank_candidate_parses_the_tool_use_block_into_the_expected_shape(db_session, monkeypatch):
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _FakeMessages.calls.clear()
    _make_anthropic_connection(db_session)

    result = rank_candidate(db_session, "JD text", {"match_score": 78}, None)

    assert result == _FAKE_TOOL_INPUT
    sent = _FakeMessages.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "submit_candidate_ranking"}
    assert "JD text" in sent["messages"][0]["content"]


def test_rank_candidate_seeds_a_published_prompt_on_first_use(db_session, monkeypatch):
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    monkeypatch.setattr(anthropic_module, "Anthropic", _FakeAnthropicClient)
    _make_anthropic_connection(db_session)

    rank_candidate(db_session, "JD text", {}, None)

    prompt = prompt_registry.get_published_prompt(db_session, TENANT, PROMPT_KEY)
    assert prompt.status == "published"
    assert "explainable ranking" in prompt.system_prompt


def test_rank_candidate_wraps_a_malformed_tool_response_in_candidate_ranking_error(db_session, monkeypatch):
    import pytest
    import app.platform.connectors.providers.anthropic_provider as anthropic_module

    class _BadFakeMessages:
        def create(self, **kwargs):
            class _Response:
                def model_dump(self):
                    return {"content": [{"type": "text", "text": "not a tool call"}], "usage": {}}
            return _Response()

    class _BadFakeClient:
        def __init__(self, api_key):
            self.messages = _BadFakeMessages()

    monkeypatch.setattr(anthropic_module, "Anthropic", _BadFakeClient)
    _make_anthropic_connection(db_session)

    with pytest.raises(CandidateRankingError):
        rank_candidate(db_session, "JD text", {}, None)
