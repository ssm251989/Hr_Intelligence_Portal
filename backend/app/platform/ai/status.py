"""Is AI set up for this company? One answer for every page (H3, Part 27).

Settings > Integrations > AI, the configuration health check and the System health page all ask this,
so they can never disagree ("connect an AI provider" while AI works). Configured means:
ai.enabled is on AND the chosen provider has what it needs -
- anthropic: the company's own key, the server's ANTHROPIC_API_KEY, or a routed AI connection;
- bedrock: a Bedrock connection / keys, or the server's AWS identity (default chain).
"""

from typing import Optional

from sqlalchemy.orm import Session


def _s(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def ai_status(db: Session, tenant) -> tuple[bool, Optional[str]]:
    """(configured, why not) -- `why not` is a plain sentence when it is not configured."""
    if not _s(db, tenant, "ai.enabled"):
        return False, "AI is switched off for your company."
    provider = _s(db, tenant, "ai.provider") or "anthropic"
    if provider == "bedrock":
        return True, None  # the AWS identity comes from the company's keys or the server's own chain (tested on the AI page)
    from app.core.config import settings as app_settings
    from app.experience.ui_genai_router import company_key
    from app.platform.connectors.router import ConnectorRouter

    if company_key(db, tenant) or app_settings.ANTHROPIC_API_KEY:
        return True, None
    router = ConnectorRouter(db)
    if any(router.try_resolve(p) is not None for p in ("llm.scoring", "llm.judgment", "llm.copilot", "llm.resume_extraction")):
        return True, None
    return False, "AI is on but no AI key or connection is set up."


def ai_configured(db: Session, tenant) -> bool:
    return ai_status(db, tenant)[0]
