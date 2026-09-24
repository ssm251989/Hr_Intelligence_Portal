"""generic_webhook provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- a plain HTTP
POST, HMAC-SHA256 signed in an X-Signature header so the receiver can verify authenticity.
The one provider bgv_generic_webhook (also Part 3's "build now" list) reuses directly --
BGV vendors integrated this way are just a webhook target with a different purpose."""

import hashlib
import hmac
import json

import httpx

from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "generic_webhook"
CAPABILITIES = ("WebhookTarget",)
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["url"],
    "properties": {"url": {"type": "string", "format": "uri"}, "timeout_seconds": {"type": "integer", "default": 10}},
}
SECRET_FIELDS = ("signing_secret",)


def _sign(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


class GenericWebhookAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.signing_secret = secrets.get("signing_secret", "")

    def send(self, url: str, payload: dict, secret: str) -> ProviderResult:
        body = json.dumps(payload).encode()
        signature = _sign(body, secret or self.signing_secret)
        try:
            response = httpx.post(
                url, content=body, headers={"Content-Type": "application/json", "X-Signature": signature},
                timeout=self.config.get("timeout_seconds", 10),
            )
            response.raise_for_status()
            return ProviderResult(success=True, raw={"status_code": response.status_code})
        except httpx.HTTPError as exc:
            return ProviderResult(success=False, error=str(exc))

    def test_connection(self) -> ProviderResult:
        return self.send(self.config["url"], {"type": "connection_test"}, self.signing_secret)

    def health_check(self) -> ProviderResult:
        return self.test_connection()
