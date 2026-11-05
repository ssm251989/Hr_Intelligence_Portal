"""anthropic provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- LlmProvider.
Module name `anthropic_provider` (not `anthropic`) to avoid shadowing the real `anthropic`
PyPI package this file itself imports."""

from anthropic import Anthropic

from app.platform.ai import model_catalog
from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "anthropic"
CAPABILITIES = ("LlmProvider",)
CONFIG_SCHEMA = {"type": "object", "properties": {}}
SECRET_FIELDS = ("api_key",)


class AnthropicAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.api_key = secrets.get("api_key", "")
        self._client: Anthropic | None = None

    def _get_client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, *, system: str, messages: list[dict], model: str, **kwargs) -> dict:
        response = self._get_client().messages.create(model=model, system=system, messages=messages, **kwargs)
        return response.model_dump()

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError("Claude (Anthropic) can't make search embeddings. Connect another AI provider for embeddings.")

    def test_connection(self) -> ProviderResult:
        try:
            self._get_client().messages.create(
                model=model_catalog.CLAUDE_HAIKU_4_5, max_tokens=1, messages=[{"role": "user", "content": "hi"}],
            )
            return ProviderResult(success=True)
        except Exception as exc:  # anthropic's own APIError hierarchy
            return ProviderResult(success=False, error=str(exc))

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=bool(self.api_key), error=None if self.api_key else "No API key configured")
