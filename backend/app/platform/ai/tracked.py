"""Part 18.23-18.25: every direct Claude call goes through here.

`tracked_client(feature=..., model_key=...)` returns an object with the same
`.messages.create(...)` / `.messages.parse(...)` the Anthropic SDK has, so the existing AI
services only change their `_get_client()`. For each call it:
1. refuses if AI or this feature is switched off, or a usage limit says "block" (18.25);
2. uses the model chosen in Settings > Integrations > AI Intelligence (`ai.models.<key>`, else
   `ai.default_model`), caps max_tokens (`ai.max_tokens_per_request`), applies the temperature
   when one is set, and retries ONCE with `ai.fallback_model` when the call fails;
3. records tokens in/out, cost, feature, module, user, what it was for (application / candidate
   from `ai_subject(...)`), ok/error and latency in ai_usage_records (18.24).
"""

import contextvars
import time
from contextlib import contextmanager
from typing import Any, Optional
from uuid import UUID

_ACTOR: contextvars.ContextVar[Optional[UUID]] = contextvars.ContextVar("ai_actor", default=None)
_SUBJECT: contextvars.ContextVar[Optional[tuple[str, UUID]]] = contextvars.ContextVar("ai_subject", default=None)


def set_actor(user_id: Optional[UUID]) -> None:
    _ACTOR.set(user_id)


@contextmanager
def ai_subject(entity_type: str, entity_id):
    """with ai_subject("application", app.id): ... -> the usage is counted for that application."""
    token = _SUBJECT.set((entity_type, entity_id))
    try:
        yield
    finally:
        _SUBJECT.reset(token)


class AIUsageBlocked(RuntimeError):
    """A usage limit (or the feature switch) stops this AI call. The message is shown to people."""


_clients: dict = {}


def forget_clients() -> None:
    _clients.clear()


def _real_client(db=None, tenant=None):
    """Settings > Integrations > AI Intelligence > Provider decides the transport:
    - "amazon_bedrock": Claude through Amazon Bedrock (AWS SDK credentials, platform/ai/bedrock.py);
    - "anthropic" (default): the company's own key when one is saved, else the server key."""
    from anthropic import Anthropic

    from app.core.config import settings
    from app.platform.ai import bedrock

    if bedrock.provider_in_use(db, tenant) == bedrock.PROVIDER:
        config = bedrock.config_for(db, tenant)
        cache_key = (bedrock.PROVIDER, *config.cache_key(), config.inference_prefix, tuple(sorted((config.model_map or {}).items())))
        if cache_key not in _clients:
            _clients[cache_key] = bedrock.BedrockClient(config)
        return _clients[cache_key]

    key = None
    if db is not None and tenant is not None:
        try:
            from app.experience.ui_genai_router import company_key

            key = company_key(db, tenant)
        except Exception:  # noqa: BLE001
            key = None
    key = key or settings.ANTHROPIC_API_KEY
    if key not in _clients:
        _clients[key] = Anthropic(api_key=key)
    return _clients[key]


def _session_and_tenant():
    from app.core.database import SessionLocal
    from app.platform.tenancy.context import get_current_tenant

    return SessionLocal(), get_current_tenant()


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        return SettingsService(db).get(key, SettingContext(tenant=tenant))
    except Exception:  # noqa: BLE001
        return None


class _Messages:
    def __init__(self, feature: str, model_key: str):
        self.feature, self.model_key = feature, model_key

    def create(self, **kwargs: Any):
        return self._call("create", kwargs)

    def parse(self, **kwargs: Any):
        return self._call("parse", kwargs)

    def _call(self, method: str, kwargs: dict):
        from app.platform.ai import governance, limits

        db, tenant = _session_and_tenant()
        try:
            module = governance.AI_FEATURES.get(self.feature, (self.feature.split(".")[0], ""))[0]
            if tenant is not None:
                if not governance.feature_enabled(db, tenant, self.feature):
                    raise AIUsageBlocked("This AI feature is switched off in Settings > Integrations > AI Intelligence.")
                limits.check(db, tenant, module=module, user_id=_ACTOR.get())
                model = _setting(db, tenant, f"ai.models.{self.model_key}") or _setting(db, tenant, "ai.default_model") or kwargs.get("model")
                cap = _setting(db, tenant, "ai.max_tokens_per_request")
                temperature = _setting(db, tenant, "ai.temperature")
                fallback = _setting(db, tenant, "ai.fallback_model")
            else:
                model, cap, temperature, fallback = kwargs.get("model"), None, None, None
            kwargs["model"] = model
            if cap:
                kwargs["max_tokens"] = min(int(kwargs.get("max_tokens") or cap), int(cap))
            if temperature not in (None, "") and "temperature" not in kwargs:
                kwargs["temperature"] = float(temperature)
            start = time.monotonic()
            try:
                response = getattr(_real_client(db, tenant).messages, method)(**kwargs)
                status = "ok"
            except Exception:
                if fallback and fallback != model:
                    kwargs["model"] = fallback
                    try:
                        response = getattr(_real_client(db, tenant).messages, method)(**kwargs)
                        status = "ok_fallback"
                    except Exception:
                        self._record(db, tenant, module, kwargs["model"], None, "error", start)
                        raise
                else:
                    self._record(db, tenant, module, model, None, "error", start)
                    raise
            self._record(db, tenant, module, kwargs["model"], response, status, start)
            return response
        finally:
            db.close()

    def _record(self, db, tenant, module, model, response, status, start):
        if tenant is None:
            return
        from app.models.intelligence import AiUsageRecord
        from app.platform.ai import governance, limits

        usage = getattr(response, "usage", None)
        tin, tout = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
        subject = _SUBJECT.get()
        try:
            db.add(AiUsageRecord(tenant_id=tenant.tenant_id, feature=self.feature, purpose=f"legacy.{self.model_key}", model=model,
                                 input_tokens=tin, output_tokens=tout, cost=governance._cost(db, tenant, model, tin, tout), module=module,
                                 user_id=_ACTOR.get(), entity_type=subject[0] if subject else None, entity_id=subject[1] if subject else None,
                                 status=status, latency_ms=int((time.monotonic() - start) * 1000)))
            db.commit()
            limits.after_call(db, tenant, module=module)
        except Exception:  # noqa: BLE001 -- counting must never break the feature itself
            db.rollback()


class TrackedClient:
    def __init__(self, feature: str, model_key: str):
        self.messages = _Messages(feature, model_key)


def tracked_client(*, feature: str, model_key: str) -> TrackedClient:
    return TrackedClient(feature, model_key)
