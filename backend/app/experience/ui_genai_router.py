"""Part 18.23-18.25 API: GenAI settings, usage dashboard, limits.

Settings (admins):
- GET  /api/v1/ui/genai/settings      what is in use today: provider, key (masked), models, per-feature on/off + model, limits
- PUT  /api/v1/ui/genai/key           {api_key} -> the company's own Anthropic key (encrypted); empty = back to the server key
- POST /api/v1/ui/genai/test          a tiny real call with the default model
- POST /api/v1/ui/genai/disconnect    AI off for the company (and the company key removed)
Usage (admins + anyone with analytics view):
- GET  /api/v1/ui/genai/usage?period=day|week|month|custom&since&until   tokens in/out, cost, requests, errors
       by module / feature / user / day, top consumers, per-candidate cost, limits status
- GET  /api/v1/ui/genai/usage/export  the same rows as CSV
"""

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.intelligence import AiUsageRecord
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/genai", tags=["ui-genai"])

# feature -> the ai.models.<key> it uses
FEATURE_MODEL_KEY = {
    "recruitment.resume_parsing": "resume_extraction", "recruitment.screening": "resume_matching", "recruitment.ranking": "candidate_ranking",
    "recruitment.shortlist_feedback": "shortlist_feedback", "recruitment.interview_kit": "interview_questions",
    "recruitment.document_check": "document_validation", "recruitment.offer_letter": "offer_letter_generation",
    "recruitment.jd_generation": "jd_generation", "copilot.chat": "candidate_ranking",
}


def _need(db, user, perm):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, perm):
        raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return tenant


def _s(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _company_connection(db, tenant):
    from app.models.connection import Connection

    return (db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.provider_code == "anthropic",
                                        Connection.status != "disabled").order_by(Connection.created_at).first())


def company_key(db, tenant) -> Optional[str]:
    conn = _company_connection(db, tenant)
    if conn is None or not conn.secret_ref:
        return None
    from app.platform.connectors.api_router import _tenant_secret_store

    try:
        return json.loads(_tenant_secret_store(db).get(conn.secret_ref) or "{}").get("api_key") or None
    except Exception:  # noqa: BLE001
        return None


def _mask(key: Optional[str]) -> Optional[str]:
    return None if not key else f"{key[:7]}…{key[-4:]}" if len(key) > 12 else "••••"


@router.get("/settings")
def genai_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.core.config import settings as app_settings
    from app.platform.ai import governance, limits

    tenant = _need(db, current_user, "platform.settings.view")
    own = company_key(db, tenant)
    conn = _company_connection(db, tenant)
    disabled = set(_s(db, tenant, "ai.features.disabled") or [])
    features = []
    for code, (module, label) in governance.AI_FEATURES.items():
        key = FEATURE_MODEL_KEY.get(code)
        features.append({"code": code, "module": module, "label": label, "enabled": governance.feature_enabled(db, tenant, code) and code not in disabled,
                         "switched_off": code in disabled, "model_key": key, "model": _s(db, tenant, f"ai.models.{key}") if key else None})
    return {
        "enabled": bool(_s(db, tenant, "ai.enabled")), "provider": _s(db, tenant, "ai.provider") or "anthropic",
        "key": {"source": "company" if own else "server" if app_settings.ANTHROPIC_API_KEY else "none",
                "masked": _mask(own or app_settings.ANTHROPIC_API_KEY),
                "last_tested_at": conn.last_tested_at.isoformat() if conn and conn.last_tested_at else None,
                "last_test_ok": (conn.last_test_result or {}).get("success") if conn else None},
        "available_models": _s(db, tenant, "ai.available_models") or [], "default_model": _s(db, tenant, "ai.default_model"),
        "fallback_model": _s(db, tenant, "ai.fallback_model"), "max_tokens_per_request": _s(db, tenant, "ai.max_tokens_per_request"),
        "temperature": _s(db, tenant, "ai.temperature"), "currency": _s(db, tenant, "ai.currency"), "pricing": _s(db, tenant, "ai.pricing") or {},
        "features": features,
        "limits": {"module_monthly_tokens": _s(db, tenant, "ai.limits.module_monthly_tokens") or {}, "user_daily_tokens": _s(db, tenant, "ai.limits.user_daily_tokens"),
                   "company_monthly_tokens": _s(db, tenant, "ai.limits.company_monthly_tokens"), "on_limit": _s(db, tenant, "ai.limits.on_limit") or {},
                   "warn_pct": _s(db, tenant, "ai.limits.warn_pct"), "reset_day": _s(db, tenant, "ai.limits.reset_day"),
                   "status": limits.status(db, tenant)},
        "modules": sorted({m for m, _l in governance.AI_FEATURES.values()}),
    }


class KeyIn(BaseModel):
    api_key: str = Field("", max_length=300)


@router.put("/key")
def set_key(body: KeyIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The company's own key lives on an "anthropic" connection (encrypted secret store)."""
    from app.models.connection import Connection
    from app.platform.connectors.api_router import _tenant_secret_store

    tenant = _need(db, current_user, "platform.settings.configure")
    conn = _company_connection(db, tenant)
    store = _tenant_secret_store(db)
    key = body.api_key.strip()
    if not key:
        if conn is not None and conn.secret_ref:
            try:
                store.delete(conn.secret_ref)
            except Exception:  # noqa: BLE001
                pass
            conn.secret_ref = None
            db.commit()
        log_action(db, "ai", None, "ai_key_removed", current_user.email[:50], {})
        return {"source": "server"}
    if conn is None:
        conn = Connection(tenant_id=tenant.tenant_id, name="Anthropic (company key)", provider_code="anthropic", capability=["LLMProvider"],
                          config_json={}, status="draft", owner_user_id=current_user.id, created_by=current_user.email)
        db.add(conn)
        db.flush()
    ref = conn.secret_ref or f"connection-{conn.id}"
    if conn.secret_ref:
        store.rotate(ref, json.dumps({"api_key": key}), created_by=current_user.email)
    else:
        store.put(ref, json.dumps({"api_key": key}), created_by=current_user.email)
    conn.secret_ref = ref
    db.commit()
    from app.platform.ai import tracked

    tracked.forget_clients()
    log_action(db, "ai", None, "ai_key_set", current_user.email[:50], {"masked": _mask(key)})
    return {"source": "company", "masked": _mask(key)}


@router.post("/test")
def test(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.platform.ai.tracked import tracked_client

    tenant = _need(db, current_user, "platform.settings.configure")
    started = datetime.now(timezone.utc)
    try:
        r = tracked_client(feature="platform.genai_test", model_key="__test__").messages.create(
            model=_s(db, tenant, "ai.default_model"), max_tokens=5, messages=[{"role": "user", "content": "Reply with OK."}])
        ok, error, model = True, None, getattr(r, "model", None)
    except Exception as exc:  # noqa: BLE001
        ok, error, model = False, str(exc)[:300], None
    conn = _company_connection(db, tenant)
    if conn is not None:
        conn.last_tested_at, conn.last_test_result = started, {"success": ok, "error": error}
        if ok:
            conn.status = "active"
        db.commit()
    return {"ok": ok, "error": error, "model": model}


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.platform.settings.resolver import SettingsService

    tenant = _need(db, current_user, "platform.settings.configure")
    SettingsService(db).set("ai.enabled", False, scope_type="tenant", scope_id=None, actor=current_user.email, tenant=tenant)
    set_key(KeyIn(api_key=""), db, current_user)
    db.commit()
    log_action(db, "ai", None, "ai_disconnected", current_user.email[:50], {})
    return {"enabled": False}


# ---------------------------------------------------------------- 18.24 usage

def _window(period: str, since: Optional[date], until: Optional[date]):
    now = datetime.now(timezone.utc)
    if period == "custom" and since:
        start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(until or now.date(), datetime.max.time(), tzinfo=timezone.utc)
    else:
        days = {"day": 1, "week": 7, "month": 30, "quarter": 90}.get(period, 30)
        start, end = now - timedelta(days=days), now
    return start, end


@router.get("/usage")
def usage(period: str = "month", since: Optional[date] = None, until: Optional[date] = None,
          db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.platform.ai import governance, limits

    tenant = require_current_tenant()
    if not (has_permission(db, tenant, current_user, "platform.settings.view") or has_permission(db, tenant, current_user, "analytics.report.view")):
        raise HTTPException(status_code=403, detail="Missing permission: platform.settings.view")
    start, end = _window(period, since, until)
    rows = db.query(AiUsageRecord).filter(AiUsageRecord.tenant_id == tenant.tenant_id, AiUsageRecord.created_at >= start, AiUsageRecord.created_at <= end).all()

    def agg(key_fn):
        d: dict = defaultdict(lambda: {"requests": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0})
        for r in rows:
            k = key_fn(r)
            x = d[k]
            x["requests"] += 1
            x["errors"] += 1 if r.status == "error" else 0
            x["tokens_in"] += r.input_tokens or 0
            x["tokens_out"] += r.output_tokens or 0
            x["cost"] += float(r.cost or 0)
        return d

    users = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.tenant_id == tenant.tenant_id)}
    labels = {c: l for c, (_m, l) in governance.AI_FEATURES.items()}
    by_module = agg(lambda r: r.module or (r.feature or "").split(".")[0] or "other")
    by_feature = agg(lambda r: r.feature)
    by_user = agg(lambda r: r.user_id)
    by_day = agg(lambda r: r.created_at.date().isoformat())
    by_model = agg(lambda r: r.model or "—")
    # per candidate: resume reading counts on the candidate; screening / documents on the application
    app_to_cand = {}
    app_ids = {r.entity_id for r in rows if r.entity_type == "application" and r.entity_id}
    if app_ids:
        app_to_cand = {a.id: a.candidate_id for a in db.query(Application).filter(Application.id.in_(app_ids))}
    per_cand = agg(lambda r: app_to_cand.get(r.entity_id) if r.entity_type == "application" else r.entity_id if r.entity_type == "candidate" else None)
    per_cand.pop(None, None)
    names = {c.id: c.full_name for c in db.query(Candidate).filter(Candidate.id.in_(list(per_cand) or [None]))} if per_cand else {}
    total = {k: sum(v[k] for v in by_module.values()) for k in ("requests", "errors", "tokens_in", "tokens_out", "cost")}

    def rows_of(d, label=lambda k: k, n=None):
        out = [{"key": str(k) if k is not None else "system", "label": label(k), **v, "tokens": v["tokens_in"] + v["tokens_out"]} for k, v in d.items()]
        out.sort(key=lambda x: -x["tokens"])
        return out[:n] if n else out

    cands = rows_of(per_cand, lambda k: names.get(k) or str(k)[:8], 20)
    return {"period": period, "since": start.isoformat(), "until": end.isoformat(), "currency": _s(db, tenant, "ai.currency"),
            "total": {**total, "tokens": total["tokens_in"] + total["tokens_out"]},
            "by_module": rows_of(by_module), "by_feature": rows_of(by_feature, lambda k: labels.get(k, k)),
            "by_user": rows_of(by_user, lambda k: users.get(k, "System (automatic)")), "by_model": rows_of(by_model),
            "by_day": sorted(rows_of(by_day), key=lambda x: x["key"]), "top_candidates": cands,
            "avg_cost_per_candidate": round(sum(c["cost"] for c in cands) / len(cands), 4) if cands else 0,
            "limits": limits.status(db, tenant), "priced": bool(_s(db, tenant, "ai.pricing"))}


@router.get("/usage/export")
def usage_export(period: str = "month", since: Optional[date] = None, until: Optional[date] = None,
                 db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "platform.settings.view")
    start, end = _window(period, since, until)
    users = {u.id: u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id)}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["when", "module", "feature", "model", "user", "tokens_in", "tokens_out", "cost", "status", "for", "latency_ms"])
    for r in db.query(AiUsageRecord).filter(AiUsageRecord.tenant_id == tenant.tenant_id, AiUsageRecord.created_at >= start,
                                            AiUsageRecord.created_at <= end).order_by(AiUsageRecord.created_at):
        w.writerow([r.created_at.isoformat(), r.module, r.feature, r.model, users.get(r.user_id, "system"), r.input_tokens, r.output_tokens,
                    float(r.cost or 0), r.status, f"{r.entity_type}:{r.entity_id}" if r.entity_type else "", r.latency_ms])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="genai-usage.csv"'})
