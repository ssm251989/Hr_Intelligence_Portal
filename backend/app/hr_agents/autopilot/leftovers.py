"""Closes approval cards whose step was already done another way (owner decision, 2026-11-19).

A card waits for HR, but the step can still happen without it: an Autopilot rule does it, HR does it
on the normal screen, or the candidate / employee moves on (withdraws, is rejected, resigns...).
Such a card is no longer a decision for anyone, so it is closed (status "closed", never "approved")
with the reason, and the agent timeline says so. Approving a leftover card was already refused by
each card's own service call; this only takes them out of My approvals.

A card is closed only when its step is clearly no longer waiting -- the person left the state the
card was made for, or the step's own "done" event was logged after the card was made. Nothing is
applied, no email is sent, no decision is made for anyone.
"""

from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import ACTOR, Run, record

# card kind -> (application states the card waits in, audit actions that mean "the step was done")
APPLICATION_STEPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "agent_interview_send": (("hr_selected",), ("interview_scheduling_started",)),
    "agent_salary_decision": (("salary_above_band",), ()),
    "agent_documents_approve": (("salary_approved",), ("documents_approved",)),
    "agent_bgv_assign": (("bgv_requested", "bgv_pending"), ("bgv_vendor_assigned",)),
    "agent_bgv_decision": (("bgv_requested", "bgv_pending"), ()),
    "agent_joining_dates": (("bgv_cleared",), ("joining_dates_proposed",)),
    "agent_interview_outcome": (("interview_scheduled",), ()),  # Part 30.3: decided on the screen -> the candidate moved on
}
JOINER_DONE = ("joined", "revoked", "declined", "no_show", "exited")
AGENT_OF = {"agent_shortlist": "screening", "agent_interview_send": "scheduling", "agent_salary_decision": "salary",
            "agent_documents_approve": "documents", "agent_bgv_assign": "bgv", "agent_bgv_decision": "bgv", "agent_joining_dates": "offer",
            "agent_mark_joined": "onboarding", "agent_resignation_approve": "exit", "agent_exit_letters": "exit", "agent_job_publish": "job",
            "agent_interview_outcome": "scheduling"}


def _who(actor: Optional[str]) -> str:
    if not actor:
        return ""
    return " by an Autopilot rule" if actor == ACTOR else f" by {actor}"


def _last_audit(db: Session, tenant, entity_id, since, actions: tuple[str, ...] = ()):
    from app.models.audit_log import AuditLog

    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_id == entity_id)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if actions:
        q = q.filter(AuditLog.action.in_(actions))
    return q.order_by(AuditLog.created_at.desc()).first()


def _uuid(value) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _application_card(db: Session, tenant, card) -> Optional[str]:
    from app.models.application import Application

    states, done_actions = APPLICATION_STEPS[card.kind]
    app_id = _uuid((card.payload_json or {}).get("application_id")) or card.entity_id
    app = db.get(Application, app_id) if app_id else None
    if app is None or app.tenant_id != tenant.tenant_id:
        return "the candidate's application no longer exists"
    if done_actions:
        done = _last_audit(db, tenant, app.id, card.created_at, done_actions)
        if done is not None:
            return f"this step was already done{_who(done.actor)}"
    if app.status not in states:
        last = _last_audit(db, tenant, app.id, card.created_at)
        return f"the candidate has moved on to '{(app.status or '').replace('_', ' ')}'{_who(last.actor if last else None)}"
    return None


def _shortlist_card(db: Session, tenant, card) -> Optional[str]:
    """A shortlist card from the HR assistant can hold several candidates: it closes only when none of them is
    still waiting in Screened (approving it would skip every one)."""
    from app.models.application import Application

    ids = [_uuid(c.get("application_id")) for c in (card.payload_json or {}).get("candidates") or [] if isinstance(c, dict)]
    ids = [i for i in ids if i] or ([card.entity_id] if card.entity_id else [])
    if not ids:
        return None
    apps = [a for a in (db.get(Application, i) for i in ids) if a is not None and a.tenant_id == tenant.tenant_id]
    if any(a.status == "screened" for a in apps):
        return None
    if not apps:
        return "the candidate's application no longer exists"
    if len(apps) == 1:
        last = _last_audit(db, tenant, apps[0].id, card.created_at)
        return f"the candidate has moved on to '{(apps[0].status or '').replace('_', ' ')}'{_who(last.actor if last else None)}"
    return "none of the candidates is waiting for a shortlist decision any more"


def _joiner_card(db: Session, tenant, card) -> Optional[str]:
    from app.models.onboarding import PreboardingCase

    case_id = _uuid((card.payload_json or {}).get("case_id")) or card.entity_id
    case = db.get(PreboardingCase, case_id) if case_id else None
    if case is None or case.tenant_id != tenant.tenant_id:
        return "the joiner no longer exists"
    if case.status in JOINER_DONE:
        last = _last_audit(db, tenant, case.id, card.created_at)
        return f"the joiner is already '{case.status.replace('_', ' ')}'{_who(last.actor if last else None)}"
    return None


def _separation(db: Session, tenant, card):
    from app.models.service_desk import Separation

    sid = _uuid((card.payload_json or {}).get("separation_id")) or card.entity_id
    s = db.get(Separation, sid) if sid else None
    return s if s is not None and s.tenant_id == tenant.tenant_id else None


def _resignation_card(db: Session, tenant, card) -> Optional[str]:
    s = _separation(db, tenant, card)
    if s is None:
        return "the resignation no longer exists"
    if s.status != "submitted" or s.approved_lwd is not None:
        last = _last_audit(db, tenant, s.id, card.created_at)
        return f"the resignation is already '{(s.status or '').replace('_', ' ')}'{_who(last.actor if last else None)}"
    return None


def _letters_card(db: Session, tenant, card) -> Optional[str]:
    s = _separation(db, tenant, card)
    if s is None:
        return "the exit no longer exists"
    if s.relieving_letter_id is not None and s.experience_letter_id is not None:
        last = _last_audit(db, tenant, s.id, card.created_at)
        return f"the letters were already issued{_who(last.actor if last else None)}"
    return None


def _job_card(db: Session, tenant, card) -> Optional[str]:
    """Part 30.1: "Publish <job>" waits while the job is still a draft; published (or deleted) by hand -> closed."""
    from app.models.job_role import JobRole

    job_id = _uuid((card.payload_json or {}).get("job_id")) or card.entity_id
    job = db.get(JobRole, job_id) if job_id else None
    if job is None or job.tenant_id != tenant.tenant_id or job.deleted_at is not None:
        return "the job no longer exists"
    if job.status == "draft":
        return None
    done = _last_audit(db, tenant, job.id, card.created_at, ("job_platforms_published",))
    who = _who(done.actor) if done is not None and done.actor != "system" else ""
    if job.status in ("published", "ready_for_publishing"):
        return f"the job was already published{who}"
    return f"the job is already '{(job.status or '').replace('_', ' ')}'{who}"


CHECKS: dict[str, Callable] = {**{kind: _application_card for kind in APPLICATION_STEPS}, "agent_shortlist": _shortlist_card, "agent_mark_joined": _joiner_card,
                               "agent_resignation_approve": _resignation_card, "agent_exit_letters": _letters_card, "agent_job_publish": _job_card}


def no_longer_waiting(db: Session, tenant, card) -> Optional[str]:
    """Why this pending card is no longer a decision for anyone, or None while it still is."""
    check = CHECKS.get(card.kind)
    return check(db, tenant, card) if check else None


def close_leftovers(db: Session, tenant, run: Run) -> int:
    from app.models.intelligence import AgentSuggestion

    closed = 0
    for card in (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.status == "pending",
                                                  AgentSuggestion.kind.in_(tuple(CHECKS))).order_by(AgentSuggestion.created_at).all()):
        why = no_longer_waiting(db, tenant, card)
        if why is None:
            continue
        card.status = "closed"
        card.closed_reason = f"Closed: {why}."[:500]
        card.reviewed_by = ACTOR
        card.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        title = card.title.split(" (Autopilot:")[0]
        record(db, tenant, run, agent=AGENT_OF.get(card.kind, "watchdog"), action="close_card", outcome="done", entity_type=card.entity_type,
               entity_id=card.entity_id, summary=f"Closed the card \"{title}\" - {why}.", details={"card_id": str(card.id), "kind": card.kind})
        closed += 1
    return closed
