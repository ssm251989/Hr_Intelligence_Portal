"""HR Agent Platform Phase 0: Amazon Bedrock transport, currency-aware AI prices, and the AI
cost per resume / job / hire.

The first group needs no database (pure functions and fake SDK clients). The second group
uses db_session, like test_llm_gateway_routing.py, and fakes the SDK client class -- never
the app's own functions -- so the real gateway / tracked-client code paths run.
"""

import uuid
from decimal import Decimal

import pytest

from app.platform.ai import bedrock, model_catalog
from app.platform.ai.unit_costs import AppRow, UsageRow, compute


# ---------------------------------------------------------------- fakes


class _FakeResponse:
    def __init__(self, model):
        self.model = model
        self.usage = type("U", (), {"input_tokens": 12, "output_tokens": 3})()
        self.content = []

    def model_dump(self):
        return {"model": self.model, "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 12, "output_tokens": 3}}


class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return _FakeResponse(kwargs.get("model"))

    def parse(self, **kwargs):
        self.calls.append(("parse", kwargs))
        return _FakeResponse(kwargs.get("model"))


class _FakeBedrockSdkClient:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = _FakeMessages()
        _FakeBedrockSdkClient.instances.append(self)


def _cfg(**kw):
    base = dict(region="ap-south-1", inference_prefix="global.", model_map={})
    base.update(kw)
    return bedrock.BedrockConfig(**base)


# ---------------------------------------------------------------- no database


def test_catalog_id_gets_the_inference_prefix():
    assert bedrock.bedrock_model_id(model_catalog.CLAUDE_HAIKU_4_5, _cfg()) == f"global.anthropic.{model_catalog.CLAUDE_HAIKU_4_5}"
    assert bedrock.bedrock_model_id(model_catalog.CLAUDE_HAIKU_4_5, _cfg(inference_prefix="")) == f"anthropic.{model_catalog.CLAUDE_HAIKU_4_5}"


def test_model_map_and_bedrock_ids_win():
    cfg = _cfg(model_map={model_catalog.CLAUDE_SONNET_5: "in.anthropic.custom-id"})
    assert bedrock.bedrock_model_id(model_catalog.CLAUDE_SONNET_5, cfg) == "in.anthropic.custom-id"
    assert bedrock.bedrock_model_id("in.anthropic.something", cfg) == "in.anthropic.something"
    arn = "arn:aws:bedrock:ap-south-1:123456789012:application-inference-profile/abc"
    assert bedrock.bedrock_model_id(arn, cfg) == arn
    assert bedrock.bedrock_model_id(None, cfg) is None


def test_config_precedence_connection_over_settings_over_server(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AWS_REGION", "server-region")
    monkeypatch.setattr(settings, "BEDROCK_INFERENCE_PREFIX", "global.")
    assert bedrock.config_from({}).region == "server-region"
    assert bedrock.config_from({}).inference_prefix == "global."
    assert bedrock.config_from({"region": "tenant-region", "inference_prefix": "in."}).region == "tenant-region"
    assert bedrock.config_from({"region": "tenant-region"}, {"region": "conn-region"}).region == "conn-region"
    assert bedrock.config_from({"inference_prefix": "none"}).inference_prefix == ""
    assert bedrock.config_from({"inference_prefix": ""}).inference_prefix == "global."  # empty = not chosen here


def test_credentials_default_to_the_aws_chain():
    assert bedrock.credential_source(bedrock.config_from({})) == "aws_default_chain"
    keys = bedrock.config_from({}, {}, {"aws_access_key_id": "AKIA-test", "aws_secret_access_key": "s"})
    assert bedrock.credential_source(keys) == "company_keys"
    assert bedrock.credential_source(bedrock.config_from({}, {}, {"bedrock_api_key": "k"})) == "bedrock_api_key"


def test_make_client_passes_region_and_keys(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "AnthropicBedrock", _FakeBedrockSdkClient)
    bedrock.make_client(_cfg())
    assert _FakeBedrockSdkClient.instances[-1].kwargs == {"aws_region": "ap-south-1"}  # no keys -> AWS default chain
    bedrock.make_client(_cfg(aws_access_key_id="AKIA-test", aws_secret_access_key="secret"))
    assert _FakeBedrockSdkClient.instances[-1].kwargs["aws_access_key"] == "AKIA-test"
    bedrock.make_client(_cfg(bedrock_api_key="br-key"))
    assert _FakeBedrockSdkClient.instances[-1].kwargs["api_key"] == "br-key"


def test_bedrock_client_swaps_only_the_model_id():
    inner = _FakeBedrockSdkClient()
    client = bedrock.BedrockClient(_cfg(), client=inner)
    kwargs = {"model": model_catalog.CLAUDE_HAIKU_4_5, "max_tokens": 10, "messages": [], "tools": [{"name": "x"}]}
    client.messages.create(**kwargs)
    client.messages.parse(**kwargs)
    (m1, sent1), (m2, sent2) = inner.messages.calls
    assert (m1, m2) == ("create", "parse")
    assert sent1["model"] == sent2["model"] == f"global.anthropic.{model_catalog.CLAUDE_HAIKU_4_5}"
    assert sent1["tools"] == [{"name": "x"}] and sent1["max_tokens"] == 10
    assert kwargs["model"] == model_catalog.CLAUDE_HAIKU_4_5  # the caller's kwargs are untouched (usage is recorded per catalog id)


def test_bedrock_adapter_reports_the_catalog_model(monkeypatch):
    import anthropic

    from app.platform.connectors.providers.bedrock_provider import BedrockAdapter

    monkeypatch.setattr(anthropic, "AnthropicBedrock", _FakeBedrockSdkClient)
    out = BedrockAdapter({"region": "ap-south-1", "inference_prefix": "in."}, {}).complete(
        system="s", messages=[{"role": "user", "content": "hi"}], model=model_catalog.CLAUDE_SONNET_5, max_tokens=5)
    assert out["model"] == model_catalog.CLAUDE_SONNET_5
    assert out["provider_model"] == f"in.anthropic.{model_catalog.CLAUDE_SONNET_5}"
    assert out["usage"]["input_tokens"] == 12


def test_price_in_another_currency_is_converted():
    from app.platform.ai.governance import price_tokens

    pricing = {"m-usd": {"input_per_mtok": 2, "output_per_mtok": 10, "currency": "USD"}, "m-local": {"input_per_mtok": 100, "output_per_mtok": 500}}
    # 1M in + 1M out at $2/$10 = $12 -> x88 = 1056 INR
    assert price_tokens(pricing, "INR", {"USD": 88}, "m-usd", 1_000_000, 1_000_000) == Decimal("1056")
    # no "currency" on the entry -> already in ai.currency, no conversion
    assert price_tokens(pricing, "INR", {"USD": 88}, "m-local", 1_000_000, 0) == Decimal("100")
    # same currency, or no rate known -> as given
    assert price_tokens(pricing, "USD", {"USD": 88}, "m-usd", 1_000_000, 0) == Decimal("2")
    assert price_tokens(pricing, "INR", {}, "m-usd", 1_000_000, 0) == Decimal("2")
    assert price_tokens(pricing, "INR", {"USD": 88}, "unknown", 1_000_000, 0) == Decimal("0")


def test_unit_costs_per_resume_job_and_hire():
    job_a, job_b = uuid.uuid4(), uuid.uuid4()
    cand_1, cand_2 = uuid.uuid4(), uuid.uuid4()
    app_1a, app_1b, app_2a = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    apps = [AppRow(app_1a, job_a, cand_1, "onboarding_completed"), AppRow(app_1b, job_b, cand_1, "screened"), AppRow(app_2a, job_a, cand_2, "screened")]
    usage = [
        UsageRow("recruitment.resume_parsing", 1.0, 100, "candidate", cand_1),   # shared by job A and B
        UsageRow("recruitment.resume_parsing", 1.0, 100, "candidate", cand_2),
        UsageRow("recruitment.screening", 0.5, 50, "application", app_1a),
        UsageRow("recruitment.screening", 0.5, 50, "application", app_2a),
        UsageRow("recruitment.jd_generation", 2.0, 300, "job", job_a),
        UsageRow("copilot.chat", 4.0, 500, None, None),                          # not tied to anything
    ]
    out = compute(usage, apps, {job_a: "Engineer", job_b: "Analyst"}, hires_in_period=1)

    assert out["total_cost"] == 9.0
    assert out["unattributed_cost"] == 4.0
    assert out["per_resume"] == {"resumes": 2, "ai_cost": 3.0, "avg": 1.5}
    rows = {r["title"]: r for r in out["per_job"]["rows"]}
    # job A: JD 2.0 + screening 1.0 + half of cand_1's reading 0.5 + cand_2's reading 1.0 = 4.5
    assert rows["Engineer"]["ai_cost"] == 4.5 and rows["Engineer"]["hires"] == 1 and rows["Engineer"]["cost_per_hire"] == 4.5
    assert rows["Engineer"]["applications"] == 2 and rows["Engineer"]["cost_per_application"] == 2.25
    assert rows["Analyst"]["ai_cost"] == 0.5 and rows["Analyst"]["cost_per_hire"] is None
    assert out["per_hire"] == {"hires": 1, "avg": 9.0}


def test_unit_costs_with_no_usage():
    out = compute([], [], {})
    assert out["per_resume"]["avg"] is None and out["per_job"]["rows"] == [] and out["per_hire"] == {"hires": 0, "avg": None}


# ---------------------------------------------------------------- with the database


def _tenant_ctx():
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext

    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _use_bedrock(db_session, monkeypatch, **extra):
    from app.platform.settings.resolver import SettingsService

    values = {"ai.provider": "amazon_bedrock", "ai.bedrock.region": "ap-south-1", "ai.bedrock.inference_prefix": "in.", **extra}
    original = SettingsService.get
    monkeypatch.setattr(SettingsService, "get", lambda self, key, ctx: values[key] if key in values else original(self, key, ctx))


def test_gateway_sends_every_purpose_through_bedrock_when_switched(db_session, monkeypatch):
    """One setting moves governed AI calls too: no route has to be edited, and a purpose with
    no route at all still works (it used to raise NoConnectionForPurposeError)."""
    import anthropic

    from app.platform.ai import gateway
    from app.platform.settings.bootstrap_definitions import register_all

    register_all()
    _FakeBedrockSdkClient.instances.clear()
    monkeypatch.setattr(anthropic, "AnthropicBedrock", _FakeBedrockSdkClient)
    _use_bedrock(db_session, monkeypatch)

    result = gateway.complete(db_session, _tenant_ctx(), purpose="test.llm.unrouted_bedrock_purpose", system="s",
                              messages=[{"role": "user", "content": "hi"}], model=model_catalog.CLAUDE_HAIKU_4_5, _record=False)

    sent = _FakeBedrockSdkClient.instances[-1].messages.calls[-1][1]
    assert sent["model"] == f"in.anthropic.{model_catalog.CLAUDE_HAIKU_4_5}"
    assert _FakeBedrockSdkClient.instances[-1].kwargs["aws_region"] == "ap-south-1"
    assert result["model"] == model_catalog.CLAUDE_HAIKU_4_5


def test_tracked_client_uses_bedrock_and_records_the_catalog_model(db_session, monkeypatch):
    import anthropic

    from app.models.intelligence import AiUsageRecord
    from app.platform.ai import tracked
    from app.platform.settings.bootstrap_definitions import register_all

    register_all()
    tracked.forget_clients()
    monkeypatch.setattr(anthropic, "AnthropicBedrock", _FakeBedrockSdkClient)
    monkeypatch.setattr(tracked, "_session_and_tenant", lambda: (db_session, _tenant_ctx()))
    monkeypatch.setattr(db_session, "close", lambda: None)
    _use_bedrock(db_session, monkeypatch, **{"ai.models.document_validation": model_catalog.CLAUDE_HAIKU_4_5})

    tracked.tracked_client(feature="recruitment.document_check", model_key="document_validation").messages.create(
        max_tokens=5, messages=[{"role": "user", "content": "hi"}])

    sent = _FakeBedrockSdkClient.instances[-1].messages.calls[-1][1]
    assert sent["model"] == f"in.anthropic.{model_catalog.CLAUDE_HAIKU_4_5}"
    record = db_session.query(AiUsageRecord).filter(AiUsageRecord.feature == "recruitment.document_check").order_by(AiUsageRecord.created_at.desc()).first()
    assert record is not None and record.model == model_catalog.CLAUDE_HAIKU_4_5
    assert record.input_tokens == 12 and record.cost > 0  # default prices (USD list) converted to INR
    tracked.forget_clients()


def test_unit_costs_endpoint_shape(client):
    response = client.get("/api/v1/ui/genai/unit-costs?period=month")
    assert response.status_code == 200, response.text
    body = response.json()
    for key in ("currency", "total_cost", "unattributed_cost", "per_resume", "per_job", "per_hire"):
        assert key in body


def test_settings_show_the_bedrock_options(client):
    response = client.get("/api/v1/ui/genai/settings")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "amazon_bedrock" in body["providers"]
    assert body["bedrock"]["credentials"] in ("aws_default_chain", "company_keys", "bedrock_api_key")
    assert body["bedrock"]["effective_region"]
