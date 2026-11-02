"""Part 18.25: GenAI usage limits (Settings > Integrations > AI Intelligence > Limits).

- ai.limits.module_monthly_tokens  {module: tokens}   e.g. {"recruitment": 1000000}; any number, empty = no limit
- ai.limits.user_daily_tokens      tokens per person per day (0 = no limit)
- ai.limits.company_monthly_tokens whole-company monthly cap (0 = no limit)
- ai.limits.on_limit               {module: "block" | "warn"}  at 100%: block AI with a friendly
                                   message, or allow and warn (default block)
- ai.limits.warn_pct               admins are told once per period when a limit reaches this % (80)
- ai.limits.reset_day              the day of the month the monthly limits start again (1-28)
Changes are audited by the settings history like every setting.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func


def _s(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        return SettingsService(db).get(key, SettingContext(tenant=tenant))
    except Exception:  # noqa: BLE001
        return None


def period_start(db, tenant, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    day = max(1, min(28, int(_s(db, tenant, "ai.limits.reset_day") or 1)))
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if now < start:  # before this month's reset day -> the period began last month
        prev = (start.replace(day=1) - timedelta(days=1)).replace(day=day)
        start = prev
    return start


def _tokens(db, tenant, since, **filters) -> int:
    from app.models.intelligence import AiUsageRecord

    q = db.query(func.coalesce(func.sum(AiUsageRecord.input_tokens + AiUsageRecord.output_tokens), 0)).filter(
        AiUsageRecord.tenant_id == tenant.tenant_id, AiUsageRecord.created_at >= since)
    for k, v in filters.items():
        q = q.filter(getattr(AiUsageRecord, k) == v)
    return int(q.scalar() or 0)


def status(db, tenant, *, module: Optional[str] = None, user_id: Optional[UUID] = None) -> list[dict]:
    """Every limit that applies, with used / limit / % -- for the usage page and for check()."""
    start = period_start(db, tenant)
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    per_module = _s(db, tenant, "ai.limits.module_monthly_tokens") or {}
    modes = _s(db, tenant, "ai.limits.on_limit") or {}
    for m, limit in per_module.items():
        if module is not None and m != module:
            continue
        if limit:
            used = _tokens(db, tenant, start, module=m)
            out.append({"scope": "module", "key": m, "limit": int(limit), "used": used, "pct": round(100 * used / int(limit), 1), "mode": modes.get(m, "block")})
    company = int(_s(db, tenant, "ai.limits.company_monthly_tokens") or 0)
    if company:
        used = _tokens(db, tenant, start)
        out.append({"scope": "company", "key": "company", "limit": company, "used": used, "pct": round(100 * used / company, 1), "mode": modes.get("company", "block")})
    daily = int(_s(db, tenant, "ai.limits.user_daily_tokens") or 0)
    if daily and user_id is not None:
        used = _tokens(db, tenant, day_start, user_id=user_id)
        out.append({"scope": "user", "key": str(user_id), "limit": daily, "used": used, "pct": round(100 * used / daily, 1), "mode": "block"})
    return out


def check(db, tenant, *, module: str, user_id: Optional[UUID]) -> None:
    from app.platform.ai.tracked import AIUsageBlocked

    for row in status(db, tenant, module=module, user_id=user_id):
        if row["used"] >= row["limit"] and row["mode"] == "block":
            what = {"module": f"the {row['key']} module", "company": "the company", "user": "your account today"}[row["scope"]]
            raise AIUsageBlocked(f"The AI usage limit for {what} is reached ({row['used']:,} of {row['limit']:,} tokens). "
                                 "It starts again at the next reset, or an admin can raise it in Settings > Integrations > AI Intelligence > Limits.")


def after_call(db, tenant, *, module: str) -> None:
    """Tell the admins (in-app, once per limit per period) at the warning % and at 100%."""
    from app.models.comms import OutboundMessage
    from app.models.user import User

    warn = int(_s(db, tenant, "ai.limits.warn_pct") or 80)
    start = period_start(db, tenant)
    admins = [u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin", User.deactivated_at.is_(None)) if u.email]
    for row in status(db, tenant, module=module):
        level = "100" if row["pct"] >= 100 else str(warn) if row["pct"] >= warn else None
        if level is None:
            continue
        tag = f"ai-limit:{row['scope']}:{row['key']}:{level}:{start.date()}"
        if db.query(OutboundMessage.id).filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.channel == "in_app",
                                               OutboundMessage.thread_key == tag).first():
            continue
        text = (f"AI usage for {'the company' if row['scope'] == 'company' else row['key']} is at {row['pct']}% of its limit "
                f"({row['used']:,} of {row['limit']:,} tokens)" + (" - AI is now " + ("blocked" if row["mode"] == "block" else "allowed with a warning") if level == "100" else "") + ".")
        for addr in admins:
            db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="ai.limit", to_addresses=[addr], subject=text,
                                   body_ref="/genai-usage", status="sent", thread_key=tag, related_entity_type="ai_limit"))
    db.commit()
