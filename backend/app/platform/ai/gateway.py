"""ai.gateway.complete(purpose=...) (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 5) -- the
one call every ai_services/*.py module is meant to migrate to eventually (NOT done yet in
this pass -- see docs/build_log.md's own Part 3 note): resolves purpose -> connection via
ConnectorRouter, model id via the Settings Registry's ai.models.* keys, then calls the
resolved connection's LlmProvider.complete().
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.connectors.router import ConnectorRouter
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

# purpose -> the ai.models.* setting key that decides which model to call it with.
_PURPOSE_MODEL_SETTING = {
    "llm.resume_extraction": "ai.models.resume_extraction",
    "llm.scoring": "ai.models.resume_matching",
    "llm.judgment": "ai.models.candidate_ranking",
    "llm.copilot": "ai.models.candidate_ranking",
    "llm.embeddings": "ai.models.resume_extraction",
}


_PURPOSE_FEATURE = {"llm.judgment": "recruitment.ranking", "llm.copilot": "copilot.chat", "llm.scoring": "recruitment.screening",
                    "llm.resume_extraction": "recruitment.resume_parsing", "llm.embeddings": "copilot.chat"}


def complete(
    db: Session, tenant: TenantContext, *, purpose: str, system: str, messages: list[dict],
    model: Optional[str] = None, **kwargs: Any,
) -> dict:
    """Never names a provider (docs/HRMS_COMPLETE_SPEC.txt Part 3's own "Code never names
    a provider or address" -- the whole point of this function existing): the caller says
    WHAT it needs (a purpose), never WHICH connection/model, exactly like every other
    ai.gateway call site will once Part 3's own migration of ai_services/*.py actually
    happens.
    """
    router = ConnectorRouter(db)
    resolved = router.resolve(purpose)
    from app.platform.connectors.registry import NotYetImplementedProviderError, get_provider

    spec = get_provider(resolved.connection.provider_code)
    if spec.adapter_cls is None:
        raise NotYetImplementedProviderError(f"{resolved.connection.provider_code} has no adapter implementation yet")

    secrets: dict = {}
    if resolved.connection.secret_ref:
        import json

        from app.models.secret import Secret, SecretScope
        from app.platform.secrets.store import get_secret_store

        store = get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))
        secrets = json.loads(store.get(resolved.connection.secret_ref))

    adapter = spec.adapter_cls(resolved.connection.config_json or {}, secrets)

    if model is None:
        setting_key = _PURPOSE_MODEL_SETTING.get(purpose, "ai.models.candidate_ranking")
        model = SettingsService(db).get(setting_key, SettingContext(tenant=tenant))

    # Part 18.24/18.25: calls that don't come through governed_complete are counted + limited here
    record = kwargs.pop("_record", True)
    feature = kwargs.pop("_feature", None) or _PURPOSE_FEATURE.get(purpose, purpose)
    if not record:
        return adapter.complete(system=system, messages=messages, model=model, **kwargs)
    import time

    from app.platform.ai import governance, limits
    from app.platform.ai.tracked import _ACTOR, _SUBJECT

    module = governance.AI_FEATURES.get(feature, (feature.split(".")[0], ""))[0]
    limits.check(db, tenant, module=module, user_id=_ACTOR.get())
    start = time.monotonic()
    status = "ok"
    try:
        result = adapter.complete(system=system, messages=messages, model=model, **kwargs)
        return result
    except Exception:
        status, result = "error", {}
        raise
    finally:
        from app.models.intelligence import AiUsageRecord

        usage = (result or {}).get("usage") or {} if isinstance(result, dict) else {}
        tin, tout = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
        subject = _SUBJECT.get()
        try:
            db.add(AiUsageRecord(tenant_id=tenant.tenant_id, feature=feature, purpose=purpose, model=model, input_tokens=tin, output_tokens=tout,
                                 cost=governance._cost(db, tenant, model, tin, tout), module=module, user_id=_ACTOR.get(),
                                 entity_type=subject[0] if subject else None, entity_id=subject[1] if subject else None, status=status,
                                 latency_ms=int((time.monotonic() - start) * 1000)))
            db.commit()
            limits.after_call(db, tenant, module=module)
        except Exception:  # noqa: BLE001
            db.rollback()


def response_text(result: dict) -> str:
    """Concatenated text blocks of a provider message dump ({"content": [{"type": "text", ...}]})."""
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type", "text") == "text")


def complete_text(db: Session, tenant: TenantContext, *, purpose: str, system: str, messages: list[dict], **kwargs: Any) -> str:
    return response_text(complete(db, tenant, purpose=purpose, system=system, messages=messages, **kwargs))


def complete_json(db: Session, tenant: TenantContext, *, purpose: str, system: str, messages: list[dict], **kwargs: Any) -> Any:
    """complete_text + tolerant JSON parse (strips a ```json fence if the model added one).
    Raises ValueError when the reply isn't JSON."""
    import json

    text_out = complete_text(db, tenant, purpose=purpose, system=system, messages=messages, **kwargs).strip()
    if text_out.startswith("```"):
        text_out = text_out.strip("`")
        text_out = text_out[4:] if text_out.lower().startswith("json") else text_out
    return json.loads(text_out)
