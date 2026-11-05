"""Daily HR briefing: at autopilot.briefing.hour (company time zone) every HR user gets
"what needs you today" -- their approval cards, what the autopilot did and escalated in the last
24 hours, today's interviews, this week's joiners and leavers. Written by AI when the feature
agents.briefing is on (plain list otherwise); in the bell, and by email when switched on."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import Run, enabled, notify, record, setting, state_get, state_set

HR_PERMISSIONS = ("recruitment.job.view", "onboarding.preboarding.view", "separation.case.view")


def facts(db: Session, tenant, user, now: Optional[datetime] = None) -> dict:
    from app.agents.service import inbox
    from app.models.autopilot import AgentActivity
    from app.models.interview import Interview
    from app.models.onboarding import PreboardingCase
    from app.models.service_desk import Separation

    now = now or datetime.now(timezone.utc)
    today = now.date()
    since = now - timedelta(hours=24)
    cards = inbox(db, tenant, user)
    acts = db.query(AgentActivity).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.created_at >= since).all()
    by = {}
    for a in acts:
        by[a.outcome] = by.get(a.outcome, 0) + 1
    interviews = db.query(func.count(Interview.id)).filter(Interview.tenant_id == tenant.tenant_id, Interview.scheduled_at >= datetime.combine(today, datetime.min.time(), timezone.utc),
                                                           Interview.scheduled_at < datetime.combine(today + timedelta(days=1), datetime.min.time(), timezone.utc)).scalar() or 0
    joiners = [c.email for c in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id,
                                                                 PreboardingCase.joining_date.between(today, today + timedelta(days=7)),
                                                                 PreboardingCase.status.notin_(("revoked", "declined", "no_show", "exited", "joined"))).limit(20)]
    leavers = db.query(func.count(Separation.id)).filter(Separation.tenant_id == tenant.tenant_id, Separation.approved_lwd.between(today, today + timedelta(days=7)),
                                                        Separation.status.in_(("approved", "clearance"))).scalar() or 0
    return {
        "approvals_waiting": [c.title for c in cards][:15], "approvals_count": len(cards),
        "autopilot_last_24h": by, "decided": [a.summary for a in acts if a.outcome == "decided"][:10],
        "escalated": [a.summary for a in acts if a.outcome == "escalated"][:10],
        "interviews_today": int(interviews), "joiners_next_7_days": joiners, "leavers_next_7_days": int(leavers),
    }


def plain(f: dict, first_name: str) -> str:
    lines = [f"Good morning {first_name}. Here is what needs you today:"]
    lines.append(f"- {f['approvals_count']} approval card(s) waiting for you" + (": " + "; ".join(f["approvals_waiting"][:5]) if f["approvals_waiting"] else "."))
    if f["escalated"]:
        lines.append("- Stuck and needs a person: " + " | ".join(f["escalated"][:5]))
    if f["decided"]:
        lines.append("- Done automatically by your company rules: " + " | ".join(f["decided"][:5]))
    lines.append(f"- Interviews today: {f['interviews_today']}. Joining in the next 7 days: {len(f['joiners_next_7_days'])}. "
                 f"Leaving in the next 7 days: {f['leavers_next_7_days']}.")
    return "\n".join(lines)


def compose(db: Session, tenant, user, f: dict) -> str:
    first = (user.full_name or user.email or "").split(" ")[0]
    base = plain(f, first)
    from app.platform.ai import governance

    try:
        res = governance.governed_complete(
            db, tenant, feature="agents.briefing", purpose="llm.copilot", actor_user_id=user.id, max_tokens=500,
            system="Write a short morning briefing for an HR person: at most 6 bullet points, most urgent first, plain words, "
                   "only facts from the data, no greetings beyond one short line.",
            messages=[{"role": "user", "content": f"Name: {first}\nData: {f}"}])
        return (res.text or "").strip() or base
    except Exception:  # noqa: BLE001 -- AI off / budget / error -> the plain list
        return base


def run(db: Session, tenant, run_: Run, now: Optional[datetime] = None) -> int:
    """Hourly; sends once per person per day, at the company's briefing hour."""
    if not enabled(db, tenant, "briefing"):
        return 0
    from zoneinfo import ZoneInfo

    from app.models.user import User
    from app.platform.iam.authz import has_permission

    now = now or datetime.now(timezone.utc)
    try:
        tz = ZoneInfo(getattr(tenant, "tz", None) or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    if local.hour != int(setting(db, tenant, "autopilot.briefing.hour") or 9) and run_.trigger != "manual":
        return 0
    day = local.date().isoformat()
    sent = 0
    for user in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.deactivated_at.is_(None)).all():
        if not user.email or not any(has_permission(db, tenant, user, p) for p in HR_PERMISSIONS):
            continue
        key = f"briefing:{user.id}"
        if (state_get(db, tenant, key) or {}).get("day") == day and run_.trigger != "manual":
            continue
        f = facts(db, tenant, user, now)
        text = compose(db, tenant, user, f)
        row = record(db, tenant, run_, agent="briefing", action="daily_briefing", outcome="done", entity_type="user", entity_id=user.id,
                     summary=f"Morning briefing for {user.email}: {f['approvals_count']} approval(s), {len(f['escalated'])} stuck item(s).",
                     details={"text": text, "facts": f})
        notify(db, tenant, [user.email], f"Your HR briefing: {f['approvals_count']} approval(s) waiting, {len(f['escalated'])} stuck item(s), "
                                         f"{f['interviews_today']} interview(s) today.", f"/autopilot?briefing={row.id}", entity_type="user", entity_id=user.id)
        if setting(db, tenant, "autopilot.briefing.email"):
            _email(db, tenant, user, text)
        state_set(db, tenant, key, {"day": day, "activity_id": str(row.id)})
        sent += 1
    return sent


def _email(db, tenant, user, text: str) -> None:
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    try:
        send_default(db, tenant, "agents.daily_briefing", to=[user.email], purpose="email.outbound.agents",
                     ctx={"first_name": (user.full_name or user.email).split(" ")[0], "briefing": text, "link": f"{public_app_url(db)}/autopilot"})
    except Exception:  # noqa: BLE001 -- the in-app briefing is already there
        db.rollback()


