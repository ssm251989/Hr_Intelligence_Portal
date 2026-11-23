"""Shared helpers for the automatic agents: switches, rules, the activity log, notifications,
cards and the small state store."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

ACTOR = "autopilot"


@dataclass
class Run:
    """How an agent was woken: by an event (with its audit action) or by a schedule / a person."""

    trigger: str = "schedule"  # event | schedule | manual
    event: Optional[str] = None


def setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def enabled(db: Session, tenant, agent: str, module: Optional[str] = None) -> bool:
    if not setting(db, tenant, "autopilot.enabled") or not setting(db, tenant, f"autopilot.{agent}.enabled"):
        return False
    if module:
        from app.platform import module_status

        return module_status.is_active(db, tenant, module)
    return True


def rule(db: Session, tenant, name: str):
    """The value of autopilot.rules.<name> (0 / False = off: a person decides)."""
    return setting(db, tenant, f"autopilot.rules.{name}")


def record(db: Session, tenant, run: Run, *, agent: str, action: str, outcome: str, summary: str, entity_type: Optional[str] = None,
           entity_id=None, rule_key: Optional[str] = None, details: Optional[dict] = None):
    from app.models.autopilot import AgentActivity

    row = AgentActivity(tenant_id=tenant.tenant_id, agent=agent, trigger=run.trigger, event=run.event, action=action, outcome=outcome,
                        rule=rule_key, entity_type=entity_type, entity_id=entity_id, summary=summary[:2000], details=_jsonable(details or {}),
                        # the wall-clock time, not now(): PostgreSQL's now() is fixed per transaction, so two steps recorded in
                        # one transaction tied and the Journey could show them in the wrong order
                        created_at=datetime.now(timezone.utc))
    db.add(row)
    db.commit()
    return row


def recently(db: Session, tenant, *, agent: str, action: str, entity_id=None, hours: float = 24) -> bool:
    """True when this agent already did `action` (for this entity) within `hours` -- keeps reruns quiet."""
    from app.models.autopilot import AgentActivity

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(AgentActivity.id).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.agent == agent, AgentActivity.action == action, AgentActivity.created_at >= since,
                                          AgentActivity.outcome != "failed")
    if entity_id is not None:
        q = q.filter(AgentActivity.entity_id == entity_id)
    return q.first() is not None


def notify(db: Session, tenant, to: list[str], subject: str, link: str, *, entity_type: Optional[str] = None, entity_id=None) -> int:
    """In-app message (the bell), like every other automatic notice in the app."""
    from app.models.comms import OutboundMessage

    sent = 0
    for addr in sorted({a for a in to if a and "@" in a}):
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="agents.autopilot", to_addresses=[addr], status="sent",
                               subject=subject[:500], body_ref=link, related_entity_type=entity_type, related_entity_id=entity_id))
        sent += 1
    db.commit()
    return sent


def admins(db: Session, tenant) -> list[str]:
    from app.recruitment.automation import _admins

    return [a for a in _admins(db, tenant) if a]


def job_people(db: Session, tenant, job) -> list[str]:
    """Job owner + hiring manager; the company's admins when the job names nobody."""
    from app.models.user import User

    ids = [i for i in (getattr(job, "created_by", None), getattr(job, "hiring_manager_id", None)) if i]
    out = [u.email for u in db.query(User).filter(User.id.in_(ids)).all() if u.email] if ids else []
    return out or admins(db, tenant)


def names(db: Session, application) -> dict:
    from app.models.candidate import Candidate
    from app.models.job_role import JobRole

    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    return {"application_id": str(application.id), "candidate": getattr(cand, "full_name", None) or "A candidate",
            "job": getattr(job, "title", None) or "", "status": application.status}


def waiting_card(db: Session, tenant, kind: str, entity_id) -> bool:
    """A card of this kind for this person already waits for HR (one step can arrive as two events, e.g. the
    salary form answer + the salary check, or each document upload + the final submit)."""
    from app.models.intelligence import AgentSuggestion

    return db.query(AgentSuggestion.id).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.entity_id == entity_id,
                                               AgentSuggestion.kind == kind, AgentSuggestion.status == "pending").first() is not None


def card(db: Session, tenant, *, kind: str, by_agent: str, title: str, payload: dict, permission: str, entity_type: str, entity_id,
         agent_column: str = "recruiter", reviewer_user_id=None, decision_log_id=None):
    """The same approval cards the HR assistant's agents raise (approvals.py applies them). `reviewer_user_id`: a named
    person who may decide besides the holders of `permission` (Part 30.3: the job's hiring manager)."""
    from app.agents.service import suggest
    from app.hr_agents import approvals  # noqa: F401 -- registers the appliers

    return suggest(db, tenant, agent=agent_column, kind=kind, title=f"{title} (Autopilot: {by_agent})",
                   payload={"by_agent": f"autopilot.{by_agent}", **payload}, reviewer_permission=permission,
                   entity_type=entity_type, entity_id=entity_id, reviewer_user_id=reviewer_user_id, decision_log_id=decision_log_id)


def state_get(db: Session, tenant, key: str, default=None):
    from app.models.autopilot import AutopilotState

    row = db.query(AutopilotState).filter(AutopilotState.tenant_id == tenant.tenant_id, AutopilotState.key == key).first()
    return row.value_json if row is not None else default


def state_set(db: Session, tenant, key: str, value) -> None:
    from app.models.autopilot import AutopilotState

    row = db.query(AutopilotState).filter(AutopilotState.tenant_id == tenant.tenant_id, AutopilotState.key == key).first()
    if row is None:
        db.add(AutopilotState(tenant_id=tenant.tenant_id, key=key, value_json=value))
    else:
        row.value_json = value
    db.commit()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
