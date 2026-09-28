"""AI governance (docs/HRMS_COMPLETE_SPEC.txt Part 12 section D): per-tenant feature
toggles, PII redaction before sending, usage metering + budget cutoff, and the AI decision
log. `governed_complete()` is the one entry point every AI feature built from Part 9 on
calls -- it wraps `gateway.complete()` (which stays the provider-agnostic transport).

Order per call: feature enabled? -> budget left? -> redact -> call -> meter -> log.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.intelligence import AiDecisionLog, AiUsageBudget, AiUsageRecord
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

# feature code -> (module, label). Code-level catalog of WHAT can be toggled; whether each
# is on is tenant data (`ai.enabled`, `ai.features.disabled`).
AI_FEATURES: dict[str, tuple[str, str]] = {
    "recruitment.jd_generation": ("recruitment", "JD drafting"),
    "recruitment.screening": ("recruitment", "Resume screening"),
    "recruitment.interview_kit": ("recruitment", "Interview kit generation"),
    "recruitment.email_summary": ("recruitment", "One-line summaries of candidate emails"),
    "recruitment.document_check": ("recruitment", "Joining document check"),
    # Part 18.23: the original AI services, now switchable and counted one by one
    "recruitment.resume_parsing": ("recruitment", "Resume reading"),
    "recruitment.ranking": ("recruitment", "Candidate ranking"),
    "recruitment.shortlist_feedback": ("recruitment", "Shortlist feedback wording"),
    "recruitment.offer_letter": ("recruitment", "Offer letter drafting"),
    "platform.genai_test": ("platform", "Connection test"),
    "onboarding.document_extraction": ("onboarding", "Document data extraction"),
    "performance.review_draft": ("performance", "Review summary drafts"),
    "separation.exit_summary": ("separation", "Exit interview summaries"),
    "copilot.chat": ("copilot", "HR Copilot"),
    "agents.recruiter": ("agents", "Recruiter agent"),
    "agents.onboarding": ("agents", "Onboarding agent"),
    "agents.helpdesk_triage": ("agents", "Helpdesk triage agent"),
    "agents.policy_checker": ("agents", "Policy checker agent"),
    "analytics.predictive": ("analytics", "Predictive estimates"),
    "platform.prompt_eval": ("platform", "Prompt evaluation runs"),
}


class AIDisabledError(Exception):
    pass


class BudgetExceededError(Exception):
    pass


def _settings(db: Session, tenant: TenantContext, key: str):
    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---- toggles ----


def feature_enabled(db: Session, tenant: TenantContext, feature: str) -> bool:
    if not _settings(db, tenant, "ai.enabled"):
        return False
    disabled = set(_settings(db, tenant, "ai.features.disabled") or [])
    module = AI_FEATURES.get(feature, (feature.split(".")[0], ""))[0]
    return feature not in disabled and f"{module}.*" not in disabled


def feature_flags(db: Session, tenant: TenantContext) -> dict:
    """For /api/me/bootstrap -- the UI hides every AI affordance whose flag is false."""
    return {"enabled": bool(_settings(db, tenant, "ai.enabled")), "features": {code: feature_enabled(db, tenant, code) for code in AI_FEATURES}}


# ---- redaction ----


@dataclass
class Redaction:
    text: str
    counts: dict


def redact(db: Session, tenant: TenantContext, text: str) -> Redaction:
    """Replaces every match of each configured pattern with `[<NAME>]`. Patterns are tenant
    settings (`ai.redaction.patterns`: {name: regex}); a bad regex is skipped, never fatal."""
    if not _settings(db, tenant, "ai.redaction.enabled"):
        return Redaction(text, {})
    counts: dict[str, int] = {}
    for name, pattern in (_settings(db, tenant, "ai.redaction.patterns") or {}).items():
        try:
            text, n = re.subn(pattern, f"[{name.upper()}]", text)
        except re.error:
            continue
        if n:
            counts[name] = n
    return Redaction(text, counts)


def _redact_messages(db: Session, tenant: TenantContext, messages: list[dict]) -> tuple[list[dict], dict]:
    totals: dict[str, int] = {}
    out = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            r = redact(db, tenant, content)
            for k, v in r.counts.items():
                totals[k] = totals.get(k, 0) + v
            out.append({**message, "content": r.text})
        else:
            out.append(message)
    return out, totals


# ---- usage budget ----


def current_period(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def usage_this_period(db: Session, tenant: TenantContext, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tokens, cost = db.query(
        func.coalesce(func.sum(AiUsageRecord.input_tokens + AiUsageRecord.output_tokens), 0), func.coalesce(func.sum(AiUsageRecord.cost), 0),
    ).filter(AiUsageRecord.tenant_id == tenant.tenant_id, AiUsageRecord.created_at >= start).one()
    return {"period": current_period(now), "tokens": int(tokens), "cost": float(cost)}


def budget_for(db: Session, tenant: TenantContext, period: str) -> Optional[AiUsageBudget]:
    return db.query(AiUsageBudget).filter(AiUsageBudget.tenant_id == tenant.tenant_id, AiUsageBudget.period == period).first()


def check_budget(db: Session, tenant: TenantContext, *, now: Optional[datetime] = None) -> None:
    usage = usage_this_period(db, tenant, now=now)
    budget = budget_for(db, tenant, usage["period"])
    if budget is None:
        return
    over_tokens = budget.token_limit is not None and usage["tokens"] >= budget.token_limit
    over_cost = budget.cost_limit is not None and Decimal(str(usage["cost"])) >= Decimal(str(budget.cost_limit))
    if over_tokens or over_cost:
        if budget.exhausted_at is None:
            budget.exhausted_at = datetime.now(timezone.utc)
            db.commit()
        raise BudgetExceededError(f"AI budget for {usage['period']} is used up")


def _maybe_alert(db: Session, tenant: TenantContext) -> None:
    usage = usage_this_period(db, tenant)
    budget = budget_for(db, tenant, usage["period"])
    if budget is None or budget.alerted_at is not None:
        return
    ratios = []
    if budget.token_limit:
        ratios.append(usage["tokens"] / budget.token_limit)
    if budget.cost_limit:
        ratios.append(usage["cost"] / float(budget.cost_limit))
    if ratios and max(ratios) * 100 >= budget.alert_pct:
        budget.alerted_at = datetime.now(timezone.utc)
        db.commit()
        from app.platform.comms.service import dispatch_event

        dispatch_event(db, tenant, "ai.budget_alert", {"period": usage["period"], "used_pct": round(max(ratios) * 100, 1), **usage})


def _cost(db: Session, tenant: TenantContext, model: Optional[str], input_tokens: int, output_tokens: int) -> Decimal:
    """Price table is tenant data (`ai.pricing`: {model: {"input_per_mtok", "output_per_mtok"}})."""
    prices = (_settings(db, tenant, "ai.pricing") or {}).get(model or "", {})
    return (Decimal(str(prices.get("input_per_mtok", 0))) * input_tokens + Decimal(str(prices.get("output_per_mtok", 0))) * output_tokens) / Decimal(1_000_000)


# ---- the governed call ----


@dataclass
class GovernedResult:
    text: str
    decision_log_id: UUID
    model: Optional[str]
    raw: dict


def governed_complete(
    db: Session, tenant: TenantContext, *, feature: str, purpose: str, system: str, messages: list[dict],
    input_refs: Optional[dict] = None, actor_user_id: Optional[UUID] = None, prompt_key: Optional[str] = None,
    prompt_version: Optional[int] = None, redact_input: bool = True, **kwargs: Any,
) -> GovernedResult:
    """`redact_input=False` only for features whose job IS reading identifiers (document
    extraction); the decision log records that redaction was skipped."""
    from app.platform.ai import gateway

    log = AiDecisionLog(tenant_id=tenant.tenant_id, feature=feature, purpose=purpose, prompt_key=prompt_key, prompt_version=prompt_version,
                        input_refs_json=input_refs or {}, actor_user_id=actor_user_id)
    if not feature_enabled(db, tenant, feature):
        log.status, log.error = "blocked", "feature disabled"
        db.add(log)
        db.commit()
        raise AIDisabledError(f"AI feature {feature!r} is turned off for this organisation")
    try:
        check_budget(db, tenant)
    except BudgetExceededError as exc:
        log.status, log.error = "blocked", str(exc)
        db.add(log)
        db.commit()
        raise

    if redact_input:
        safe_messages, counts = _redact_messages(db, tenant, messages)
        safe_system = redact(db, tenant, system)
        for k, v in safe_system.counts.items():
            counts[k] = counts.get(k, 0) + v
    else:
        safe_messages, safe_system, counts = messages, Redaction(system, {}), {"skipped": True}
    log.redactions_json = counts
    try:
        from app.platform.ai import limits
        from app.platform.ai.tracked import _ACTOR

        limits.check(db, tenant, module=AI_FEATURES.get(feature, (feature.split(".")[0], ""))[0], user_id=actor_user_id or _ACTOR.get())
        raw = gateway.complete(db, tenant, purpose=purpose, system=safe_system.text, messages=safe_messages, _record=False, **kwargs)
    except Exception as exc:
        log.status, log.error = "error", type(exc).__name__
        db.add(log)
        db.commit()
        raise
    text_out = gateway.response_text(raw)
    usage = (raw.get("usage") or {}) if isinstance(raw, dict) else {}
    model = raw.get("model") if isinstance(raw, dict) else None
    input_tokens, output_tokens = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    log.model = model
    log.output_json = {"text": text_out}
    log.final_decision = "pending"
    db.add(log)
    db.flush()
    from app.platform.ai.tracked import _ACTOR, _SUBJECT

    subject = _SUBJECT.get()
    db.add(AiUsageRecord(tenant_id=tenant.tenant_id, feature=feature, purpose=purpose, model=model, input_tokens=input_tokens,
                         output_tokens=output_tokens, cost=_cost(db, tenant, model, input_tokens, output_tokens), decision_log_id=log.id,
                         module=AI_FEATURES.get(feature, (feature.split(".")[0], ""))[0], user_id=actor_user_id or _ACTOR.get(),
                         entity_type=subject[0] if subject else None, entity_id=subject[1] if subject else None, status="ok"))
    db.commit()
    _maybe_alert(db, tenant)
    return GovernedResult(text=text_out, decision_log_id=log.id, model=model, raw=raw)


def governed_json(db: Session, tenant: TenantContext, **kwargs: Any) -> tuple[Any, UUID]:
    import json

    result = governed_complete(db, tenant, **kwargs)
    text_out = result.text.strip()
    if text_out.startswith("```"):
        text_out = text_out.strip("`")
        text_out = text_out[4:] if text_out.lower().startswith("json") else text_out
    return json.loads(text_out), result.decision_log_id


def record_human_decision(db: Session, tenant: TenantContext, decision_log_id: Optional[UUID], *, reviewer: str, decision: str) -> None:
    if decision_log_id is None:
        return
    log = db.query(AiDecisionLog).filter(AiDecisionLog.tenant_id == tenant.tenant_id, AiDecisionLog.id == decision_log_id).first()
    if log is not None:
        log.human_reviewer, log.final_decision, log.decided_at = reviewer, decision, datetime.now(timezone.utc)
        db.commit()
