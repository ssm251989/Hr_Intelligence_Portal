"""amazon_bedrock provider -- LlmProvider through Amazon Bedrock (HR Agent Platform, Phase 0).

A connection of this provider holds the company's own AWS setup: region, inference prefix,
model id map (config) and, optionally, keys (secrets). With no keys it uses the AWS SDK's
default credential chain (the server's IAM role / env / profile), which is the normal set-up
on AWS. Results come back in the same dict shape the anthropic adapter returns, with `model`
set to the catalog id the caller asked for, so usage, prices and logs stay comparable.
"""

from app.platform.ai import bedrock, model_catalog
from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = bedrock.PROVIDER
CAPABILITIES = ("LlmProvider",)
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "region": {"type": "string", "description": "AWS region, e.g. ap-south-1"},
        "inference_prefix": {"type": "string", "enum": ["global.", "in.", "apac.", "none"],
                             "description": "global. = global cross-region inference, in. = India only, none = in-region"},
        "model_map": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "catalog model id -> Bedrock model id or inference profile ARN"},
    },
}
SECRET_FIELDS = ("aws_access_key_id", "aws_secret_access_key", "aws_session_token", "bedrock_api_key")


class BedrockAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = bedrock.config_from({}, config or {}, secrets or {})
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = bedrock.BedrockClient(self.config)
        return self._client

    def complete(self, *, system: str, messages: list[dict], model: str, **kwargs) -> dict:
        response = self._get_client().messages.create(model=model, system=system, messages=messages, **kwargs)
        out = response.model_dump()
        out["model"] = model  # the catalog id -- prices and usage are kept per catalog id
        out["provider_model"] = bedrock.bedrock_model_id(model, self.config)
        return out

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError("Claude on Bedrock can't make search embeddings. Connect an embeddings provider for that.")

    def test_connection(self) -> ProviderResult:
        try:
            self._get_client().messages.create(model=model_catalog.CLAUDE_HAIKU_4_5, max_tokens=1, messages=[{"role": "user", "content": "hi"}])
            return ProviderResult(success=True)
        except Exception as exc:  # botocore / anthropic errors
            return ProviderResult(success=False, error=str(exc))

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=bool(self.config.region), error=None if self.config.region else "No AWS region configured")
