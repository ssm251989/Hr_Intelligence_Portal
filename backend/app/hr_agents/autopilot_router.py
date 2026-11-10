"""Part 26: the Autopilot page -- what the automatic agents did, their switches and rules, Run now."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.autopilot import AUTOPILOT_AGENTS, OUTCOMES, AgentActivity
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/autopilot", tags=["ui-autopilot"])

VIEW = ("recruitment.job.view", "onboarding.preboarding.view", "separation.case.view", "platform.settings.view")
CONFIGURE = "platform.settings.configure"
RULES = ("shortlist_min_score", "salary_max_over_band_pct", "documents_auto_approve", "bgv_auto_assign_vendor", "bgv_auto_pass_clear_report",
         "joining_dates_auto", "joining_dates_after_days", "mark_joined_when_ready", "exit_letters_auto")
OTHER = ("watchdog.stale_hours", "sourcing.min_strong", "briefing.hour", "briefing.email")


def _viewer(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    tenant = require_current_tenant()
    if not any(has_permission(db, tenant, user, p) for p in VIEW):
        raise HTTPException(status_code=403, detail="Missing permission")
    return user


def _item(a: AgentActivity) -> dict:
    return {"id": str(a.id), "agent": a.agent, "trigger": a.trigger, "event": a.event, "action": a.action, "outcome": a.outcome, "rule": a.rule,
            "entity_type": a.entity_type, "entity_id": str(a.entity_id) if a.entity_id else None, "summary": a.summary,
            "at": a.created_at.isoformat() if a.created_at else None, "link": _link(a)}


def _link(a: AgentActivity) -> Optional[str]:
    card = (a.details or {}).get("card_id")
    if card:
        return "/approvals"
    if a.entity_type == "application" and a.entity_id:
        return f"/candidates/{a.entity_id}"
    return {"job_role": f"/jobs/{a.entity_id}", "separation": "/exits", "preboarding_case": "/onboarding"}.get(a.entity_type or "")


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(_viewer)):
    from app.hr_agents.autopilot.core import setting
    from app.platform.jobs import inapp

    tenant = require_current_tenant()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    counts = {}
    for agent, outcome, n in (db.query(AgentActivity.agent, AgentActivity.outcome, func.count(AgentActivity.id))
                              .filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.created_at >= since)
                              .group_by(AgentActivity.agent, AgentActivity.outcome)):
        counts.setdefault(agent, {})[outcome] = n
    try:
        jobs = {k: v for k, v in inapp.status().items() if k.startswith("autopilot_")}
    except Exception:  # noqa: BLE001 -- the control plane may be unreachable in tests
        jobs = {}
    return {
        "enabled": bool(setting(db, tenant, "autopilot.enabled")),
        "agents": [{"key": a, "enabled": bool(setting(db, tenant, f"autopilot.{a}.enabled")), "last_7_days": counts.get(a, {})} for a in AUTOPILOT_AGENTS],
        "rules": {r: setting(db, tenant, f"autopilot.rules.{r}") for r in RULES},
        "options": {o: setting(db, tenant, f"autopilot.{o}") for o in OTHER},
        "jobs": jobs, "can_configure": has_permission(db, tenant, user, CONFIGURE),
    }


@router.get("/waiting")
def waiting(db: Session = Depends(get_db), user: User = Depends(_viewer)):
    """Part 29: the approval cards the agents prepared that this person can decide (same cards as My approvals)."""
    from app.agents.service import inbox, suggestion_to_dict

    tenant = require_current_tenant()
    rows = [s for s in inbox(db, tenant, user) if (s.kind or "").startswith("agent_") or str((s.payload_json or {}).get("by_agent") or "").startswith("autopilot.")]
    return {"items": [{**suggestion_to_dict(s), "by_agent": (s.payload_json or {}).get("by_agent")} for s in rows]}


@router.get("/journey/{application_id}")
def journey(application_id: UUID, db: Session = Depends(get_db), user: User = Depends(_viewer)):
    """Part 29: one candidate's story as the agents saw it, oldest first."""
    tenant = require_current_tenant()
    rows = (db.query(AgentActivity).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.entity_type == "application",
                                           AgentActivity.entity_id == application_id).order_by(AgentActivity.created_at.asc()).limit(200).all())
    return {"items": [_item(a) for a in rows]}


@router.get("/activity")
def activity(agent: Optional[str] = None, outcome: Optional[str] = None, before: Optional[datetime] = None, limit: int = 50,
             db: Session = Depends(get_db), user: User = Depends(_viewer)):
    tenant = require_current_tenant()
    q = db.query(AgentActivity).filter(AgentActivity.tenant_id == tenant.tenant_id)
    if agent:
        if agent not in AUTOPILOT_AGENTS:
            raise HTTPException(status_code=400, detail="unknown agent")
        q = q.filter(AgentActivity.agent == agent)
    if outcome:
        if outcome not in OUTCOMES:
            raise HTTPException(status_code=400, detail="unknown outcome")
        q = q.filter(AgentActivity.outcome == outcome)
    if before:
        q = q.filter(AgentActivity.created_at < before)
    rows = q.order_by(AgentActivity.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return {"items": [_item(a) for a in rows]}


@router.get("/activity/{activity_id}")
def activity_item(activity_id: UUID, db: Session = Depends(get_db), user: User = Depends(_viewer)):
    tenant = require_current_tenant()
    a = db.get(AgentActivity, activity_id)
    if a is None or a.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="Not found")
    if a.agent == "briefing" and a.entity_id != user.id and not has_permission(db, tenant, user, CONFIGURE):
        raise HTTPException(status_code=404, detail="Not found")  # a briefing is personal
    return {**_item(a), "details": a.details or {}}


class SettingIn(BaseModel):
    value: Any


@router.put("/settings/{key}")
def set_setting(key: str, body: SettingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.platform.settings.resolver import SettingsService

    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, CONFIGURE):
        raise HTTPException(status_code=403, detail=f"Missing permission: {CONFIGURE}")
    allowed = {"autopilot.enabled"} | {f"autopilot.{a}.enabled" for a in AUTOPILOT_AGENTS} | {f"autopilot.rules.{r}" for r in RULES} | {f"autopilot.{o}" for o in OTHER}
    if key not in allowed:
        raise HTTPException(status_code=404, detail="Not an Autopilot setting")
    try:
        SettingsService(db).set(key, body.value, scope_type="tenant", scope_id=None, actor=user.email, tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.audit.service import log_action

    log_action(db, "setting", None, "autopilot_setting_changed", user.email[:50], {"key": key, "value": body.value})
    return {"key": key, "value": body.value}


@router.post("/run/{what}")
def run_now(what: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.hr_agents.autopilot.core import setting
    from app.hr_agents.autopilot.runner import RUN_NOW

    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, CONFIGURE):
        raise HTTPException(status_code=403, detail=f"Missing permission: {CONFIGURE}")
    if what not in RUN_NOW:
        raise HTTPException(status_code=404, detail="Nothing to run")
    if not setting(db, tenant, "autopilot.enabled"):
        raise HTTPException(status_code=400, detail="Autopilot is off - switch it on first.")
    return {"result": RUN_NOW[what](db, tenant)}
