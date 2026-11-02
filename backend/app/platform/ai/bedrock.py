"""Amazon Bedrock as the AI transport (HR Agent Platform proposal, Phase 0: "one AI gateway on
Amazon Bedrock using the AWS SDK").

Every Claude call in this app speaks the Anthropic Messages shape (`messages.create`,
`messages.parse`, tool use, `response.usage`). Bedrock serves that same shape through
InvokeModel, and the anthropic SDK's `AnthropicBedrock` client signs those requests with the
AWS SDK's own credential chain (env vars, IAM role, AWS profile) -- so switching provider is
a transport change, not a rewrite of every AI service.

Two things differ from calling Anthropic directly, and both live here:
1. Model ids. The app keeps using the catalog ids (`model_catalog.py`, the `ai.models.*`
   settings, usage records, prices). Only the request sent to Bedrock carries the Bedrock id:
   `ai.bedrock.model_map[catalog_id]` when set, else `<inference prefix>anthropic.<catalog_id>`
   (prefix `global.` = global cross-region inference, `in.` = India-only, `` = in-region).
   Check the exact ids in the Bedrock console (Model catalog) and put any that differ in
   `ai.bedrock.model_map`.
2. Credentials. No API key: the AWS credential chain by default, or a Bedrock connection's
   own keys (`aws_access_key_id` / `aws_secret_access_key`, or a `bedrock_api_key`).
"""

from dataclasses import dataclass, field
from typing import Any, Optional

PROVIDER = "amazon_bedrock"

# Bedrock ids already look like these; anything else is a catalog id to translate.
_BEDROCK_ID_MARKERS = ("anthropic.", "arn:aws:")


@dataclass(frozen=True)
class BedrockConfig:
    region: str
    inference_prefix: str = ""
    model_map: dict = field(default_factory=dict)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_session_token: Optional[str] = None
    bedrock_api_key: Optional[str] = None

    def cache_key(self) -> tuple:
        return (self.region, self.aws_access_key_id or "", self.aws_secret_access_key or "", self.aws_session_token or "", self.bedrock_api_key or "")


def bedrock_model_id(model: Optional[str], config: BedrockConfig) -> Optional[str]:
    """Catalog id -> the id Bedrock expects. Bedrock ids and ARNs pass through unchanged."""
    if not model:
        return model
    mapped = (config.model_map or {}).get(model)
    if mapped:
        return mapped
    if any(marker in model for marker in _BEDROCK_ID_MARKERS):
        return model
    return f"{config.inference_prefix or ''}anthropic.{model}"


def make_client(config: BedrockConfig):
    """An `AnthropicBedrock` client (same `.messages` surface as `Anthropic`)."""
    from anthropic import AnthropicBedrock

    kwargs: dict[str, Any] = {"aws_region": config.region}
    if config.bedrock_api_key:
        kwargs["api_key"] = config.bedrock_api_key
    elif config.aws_access_key_id and config.aws_secret_access_key:
        kwargs.update(aws_access_key=config.aws_access_key_id, aws_secret_key=config.aws_secret_access_key)
        if config.aws_session_token:
            kwargs["aws_session_token"] = config.aws_session_token
    return AnthropicBedrock(**kwargs)


class _BedrockMessages:
    """`.messages` with the catalog -> Bedrock model id swap. Everything else (system, tools,
    tool_choice, output_format, max_tokens, temperature) goes through untouched."""

    def __init__(self, inner, config: BedrockConfig):
        self._inner, self._config = inner, config

    def create(self, **kwargs: Any):
        return self._inner.create(**self._translate(kwargs))

    def parse(self, **kwargs: Any):
        return self._inner.parse(**self._translate(kwargs))

    def _translate(self, kwargs: dict) -> dict:
        out = dict(kwargs)
        if "model" in out:
            out["model"] = bedrock_model_id(out["model"], self._config)
        return out


class BedrockClient:
    """What `tracked._real_client()` hands back when the provider is Bedrock."""

    def __init__(self, config: BedrockConfig, client=None):
        self.config = config
        self.messages = _BedrockMessages((client or make_client(config)).messages, config)


# ---- where the config comes from ----


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        return SettingsService(db).get(key, SettingContext(tenant=tenant))
    except Exception:  # noqa: BLE001
        return None


def provider_in_use(db, tenant) -> str:
    """`ai.provider` -- "anthropic" (direct API) or "amazon_bedrock"."""
    if db is None or tenant is None:
        from app.core.config import settings

        return settings.AI_PROVIDER or "anthropic"
    return _setting(db, tenant, "ai.provider") or "anthropic"


def company_connection(db, tenant):
    """The company's own Bedrock connection, if it added one (own AWS account / keys)."""
    from app.models.connection import Connection

    return (db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.provider_code == PROVIDER,
                                        Connection.status != "disabled").order_by(Connection.created_at).first())


def _connection_secrets(db, tenant, conn) -> dict:
    if conn is None or not conn.secret_ref:
        return {}
    import json

    from app.models.secret import Secret, SecretScope
    from app.platform.secrets.store import get_secret_store

    try:
        return json.loads(get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id)).get(conn.secret_ref) or "{}")
    except Exception:  # noqa: BLE001
        return {}


def config_from(settings_values: dict, connection_config: Optional[dict] = None, secrets: Optional[dict] = None) -> BedrockConfig:
    """Precedence: the company's Bedrock connection > tenant settings (ai.bedrock.*) > server env."""
    from app.core.config import settings

    conn_cfg, secrets = connection_config or {}, secrets or {}
    # empty = "not chosen here"; the explicit choice "none" = in-region model ids, no prefix
    prefix = conn_cfg.get("inference_prefix") or settings_values.get("inference_prefix") or settings.BEDROCK_INFERENCE_PREFIX
    return BedrockConfig(
        region=conn_cfg.get("region") or settings_values.get("region") or settings.AWS_REGION,
        inference_prefix="" if prefix in (None, "none") else prefix,
        model_map={**(settings_values.get("model_map") or {}), **(conn_cfg.get("model_map") or {})},
        aws_access_key_id=secrets.get("aws_access_key_id") or None,
        aws_secret_access_key=secrets.get("aws_secret_access_key") or None,
        aws_session_token=secrets.get("aws_session_token") or None,
        bedrock_api_key=secrets.get("bedrock_api_key") or None,
    )


def config_for(db, tenant) -> BedrockConfig:
    if db is None or tenant is None:
        return config_from({})
    conn = company_connection(db, tenant)
    values = {"region": _setting(db, tenant, "ai.bedrock.region"), "inference_prefix": _setting(db, tenant, "ai.bedrock.inference_prefix"),
              "model_map": _setting(db, tenant, "ai.bedrock.model_map")}
    return config_from(values, conn.config_json if conn is not None else None, _connection_secrets(db, tenant, conn))


def credential_source(config: BedrockConfig) -> str:
    """For the settings page: where the AWS identity comes from (never the secret itself)."""
    if config.bedrock_api_key:
        return "bedrock_api_key"
    if config.aws_access_key_id:
        return "company_keys"
    return "aws_default_chain"
