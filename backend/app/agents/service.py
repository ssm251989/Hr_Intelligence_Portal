"""Background AI agents, always human-in-the-loop (docs/HRMS_COMPLETE_SPEC.txt Part 12 C).

An agent never changes business data. It writes an `agent_suggestions` row that lands in
the reviewer's inbox; only `decide()` with approve/edit runs the suggestion's applier
(registered per `kind`), and the decision is written back to the AI decision log for
audit and bias review. Agents:
- recruiter: JD drafts, interview kits, sourcing shortlist (existing candidates whose
  suitability already points at the job but who haven't applied);
- onboarding: chases missing pre-boarding documents;
- helpdesk_triage: suggests category / priority / a first answer for a ticket;
- policy_checker: reviews a policy/KB text for gaps and conflicts.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.intelligence import AgentSuggestion
from app.models.user import User
from app.platform.ai import governance
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import TenantContext


class AgentError(ValueError):
    pass


# kind -> applier(db, tenant, suggestion, final_payload, reviewer_email)
_APPLIERS: dict[str, Callable] = {}


def applier(kind: str):
    def _register(fn):
        _APPLIERS[kind] = fn
        return fn
    return _register


def suggest(db: Session, tenant: TenantContext, *, agent: str, kind: str, title: str, payload: dict, reviewer_permission: str,
            entity_type: Optional[str] = None, entity_id: Optional[UUID] = None, reviewer_user_id: Optional[UUID] = None,
            decision_log_id: Optional[UUID] = None) -> AgentSuggestion:
    existing = db.query(AgentSuggestion).filter(
        AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == kind, AgentSuggestion.entity_id == entity_id, AgentSuggestion.status == "pending",
    ).first() if entity_id else None
    if existing is not None:
        return existing  # one open suggestion per (kind, entity) -- re-running an agent doesn't spam the inbox
    row = AgentSuggestion(tenant_id=tenant.tenant_id, agent=agent, kind=kind, title=title, payload_json=payload, reviewer_permission=reviewer_permission,
                          entity_type=entity_type, entity_id=entity_id, reviewer_user_id=reviewer_user_id, decision_log_id=decision_log_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def inbox(db: Session, tenant: TenantContext, user: User) -> list[AgentSuggestion]:
    rows = db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.status == "pending").order_by(AgentSuggestion.created_at.asc()).all()
    return [r for r in rows if r.reviewer_user_id == user.id or has_permission(db, tenant, user, r.reviewer_permission)]


def decide(db: Session, tenant: TenantContext, suggestion: AgentSuggestion, *, user: User, action: str, edited_payload: Optional[dict] = None) -> AgentSuggestion:
    if action not in ("approve", "edit", "reject"):
        raise AgentError("action is approve, edit or reject")
    if suggestion.status != "pending":
        raise AgentError(f"suggestion already {suggestion.status}")
    if suggestion.reviewer_user_id != user.id and not has_permission(db, tenant, user, suggestion.reviewer_permission):
        raise PermissionError(suggestion.reviewer_permission)
    final = edited_payload if action == "edit" else suggestion.payload_json
    if action in ("approve", "edit") and suggestion.kind in _APPLIERS:
        _APPLIERS[suggestion.kind](db, tenant, suggestion, final, user.email)
    suggestion.status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[action]
    suggestion.final_payload_json = final if action != "reject" else None
    suggestion.reviewed_by = user.email
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    governance.record_human_decision(db, tenant, suggestion.decision_log_id, reviewer=user.email,
                                     decision={"approve": "accepted", "edit": "edited", "reject": "rejected"}[action])
    db.refresh(suggestion)
    return suggestion


# ---- recruiter agent ----


def recruiter_jd_draft(db: Session, tenant: TenantContext, job_role_id: UUID) -> AgentSuggestion:
    from app.models.job_role import JobRole

    job = db.get(JobRole, job_role_id)
    if job is None:
        raise AgentError("job not found")
    result = governance.governed_complete(
        db, tenant, feature="agents.recruiter", purpose="llm.judgment",
        system="Draft a clear, inclusive job description from the role inputs. Plain text with headings. Never invent a salary, benefit or requirement not given.",
        messages=[{"role": "user", "content": f"Title: {job.title}\nDepartment: {job.department}\nLocation: {job.location}\nResponsibilities: {job.key_responsibilities or ''}\n"
                                                f"Must-have skills: {job.technical_skills_must_have or []}\nGood-to-have: {job.technical_skills_good_to_have or []}"}],
        input_refs={"job_role_id": str(job.id)},
    )
    return suggest(db, tenant, agent="recruiter", kind="jd_draft", title=f"JD draft for {job.title}", payload={"jd_text": result.text},
                   reviewer_permission="recruitment.job.edit", entity_type="job_role", entity_id=job.id, decision_log_id=result.decision_log_id)


@applier("jd_draft")
def _apply_jd(db, tenant, suggestion, payload, reviewer):
    from app.models.job_role import JobRole

    job = db.get(JobRole, suggestion.entity_id)
    if job is not None:
        job.jd_text = payload.get("jd_text")
        db.commit()


def recruiter_interview_kit(db: Session, tenant: TenantContext, job_role_id: UUID) -> AgentSuggestion:
    from app.models.job_role import JobRole

    job = db.get(JobRole, job_role_id)
    if job is None:
        raise AgentError("job not found")
    kit, log_id = governance.governed_json(
        db, tenant, feature="agents.recruiter", purpose="llm.judgment",
        system='Create an interview kit as JSON: {"competencies": [{"name", "questions": [..], "what_good_looks_like"}], "scorecard": [..]}. Job-related, legal, unbiased questions only.',
        messages=[{"role": "user", "content": f"Role: {job.title}\nSkills: {job.technical_skills_must_have or []}\nResponsibilities: {job.key_responsibilities or ''}"}],
        input_refs={"job_role_id": str(job.id)},
    )
    return suggest(db, tenant, agent="recruiter", kind="interview_kit", title=f"Interview kit for {job.title}", payload={"kit": kit},
                   reviewer_permission="recruitment.interview.edit", entity_type="job_role", entity_id=job.id, decision_log_id=log_id)


def recruiter_sourcing_shortlist(db: Session, tenant: TenantContext, job_role_id: UUID, *, limit: int = 10) -> Optional[AgentSuggestion]:
    """Deterministic (no LLM): candidates the existing suitability engine already matched to
    this job who have no application for it yet."""
    from app.models.application import Application
    from app.models.candidate import Candidate

    applied = {a.candidate_id for a in db.query(Application.candidate_id).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job_role_id).all()}
    rows = (
        db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.suitable_job_id == job_role_id)
        .order_by(Candidate.suitable_job_score.desc().nulls_last()).limit(limit * 3).all()
    )
    picks = [{"candidate_id": str(c.id), "name": c.full_name, "score": float(c.suitable_job_score) if c.suitable_job_score is not None else None}
             for c in rows if c.id not in applied][:limit]
    if not picks:
        return None
    return suggest(db, tenant, agent="recruiter", kind="sourcing_shortlist", title=f"{len(picks)} existing candidates may fit this job", payload={"candidates": picks},
                   reviewer_permission="recruitment.application.create", entity_type="job_role", entity_id=job_role_id)


# ---- onboarding agent ----


def onboarding_chase_documents(db: Session, tenant: TenantContext, *, within_days: int = 14, today: Optional[date] = None) -> list[AgentSuggestion]:
    from app.models.onboarding import PreboardingCase
    from app.onboarding.portal import PreboardingPortal

    if not governance.feature_enabled(db, tenant, "agents.onboarding"):
        raise governance.AIDisabledError("onboarding agent is turned off")
    today = today or datetime.now(timezone.utc).date()
    portal = PreboardingPortal(db, tenant)
    out = []
    for case in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status.in_(("invited", "in_progress")),
                                                 PreboardingCase.joining_date.between(today, today + timedelta(days=within_days))).all():
        readiness = portal.readiness(case)
        uploaded = {d.document_type_code for d in portal.documents(case)}
        missing = [d for d in readiness["documents"]["required"] if d not in uploaded]
        if missing:
            out.append(suggest(db, tenant, agent="onboarding", kind="chase_documents", title=f"{case.email}: {len(missing)} document(s) missing",
                               payload={"case_id": str(case.id), "email": case.email, "missing": missing, "joining_date": case.joining_date.isoformat()},
                               reviewer_permission="onboarding.preboarding.edit", entity_type="preboarding_case", entity_id=case.id))
    return out


@applier("chase_documents")
def _apply_chase(db, tenant, suggestion, payload, reviewer):
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, "onboarding.documents_reminder", {**payload, "approved_by": reviewer})


# ---- helpdesk triage agent ----


def helpdesk_triage(db: Session, tenant: TenantContext, ticket_id: UUID) -> AgentSuggestion:
    from app.models.metadata import MasterValue
    from app.models.service_desk import Ticket
    from app.service_desk import tickets as ticket_service

    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.tenant_id != tenant.tenant_id:
        raise AgentError("ticket not found")
    if ticket.confidential:
        raise AgentError("confidential tickets are never sent to AI triage")
    categories = [v.code for v in db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "ticket_category", MasterValue.is_active.is_(True)).all()]
    kb = ticket_service.search_kb(db, tenant, f"{ticket.subject} {ticket.description or ''}", limit=3)
    suggestion, log_id = governance.governed_json(
        db, tenant, feature="agents.helpdesk_triage", purpose="llm.scoring",
        system=('Triage an HR helpdesk ticket. Reply JSON {"category": one of the given codes, "priority": "low"|"medium"|"high"|"urgent", '
                '"answer": a short suggested reply using ONLY the knowledge-base excerpts or null, "reason": one sentence}.'),
        messages=[{"role": "user", "content": f"Categories: {categories}\nSubject: {ticket.subject}\nDescription: {ticket.description or ''}\n"
                                                f"KB: {[{'title': a.title, 'excerpt': a.body[:400]} for a in kb]}"}],
        input_refs={"ticket_id": str(ticket.id)},
    )
    if suggestion.get("category") not in categories:
        suggestion["category"] = ticket.category_code
    ticket.ai_suggestion_json = suggestion
    db.commit()
    return suggest(db, tenant, agent="helpdesk_triage", kind="ticket_triage", title=f"Triage {ticket.number}", payload=suggestion,
                   reviewer_permission="helpdesk.ticket.edit", entity_type="ticket", entity_id=ticket.id, decision_log_id=log_id)


@applier("ticket_triage")
def _apply_triage(db, tenant, suggestion, payload, reviewer):
    from app.models.service_desk import Ticket
    from app.service_desk import tickets as ticket_service

    ticket = db.get(Ticket, suggestion.entity_id)
    if ticket is None:
        return
    changed = False
    if payload.get("category") and payload["category"] != ticket.category_code:
        ticket.category_code, changed = payload["category"], True
    if payload.get("priority") in ("low", "medium", "high", "urgent") and payload["priority"] != ticket.priority:
        ticket.priority, changed = payload["priority"], True
    if changed:
        ticket_service.apply_sla(db, tenant, ticket, start=ticket.created_at)
    db.commit()
    if payload.get("answer"):
        ticket_service.add_comment(db, tenant, ticket, author=reviewer, body=payload["answer"], is_agent=True)


# ---- policy checker agent ----


def policy_check(db: Session, tenant: TenantContext, *, title: str, text_body: str, entity_type: Optional[str] = None, entity_id: Optional[UUID] = None) -> AgentSuggestion:
    from app.copilot import retrieval

    related = retrieval.search(db, tenant, f"{title} {text_body[:400]}", role_names=[], k=3)
    review, log_id = governance.governed_json(
        db, tenant, feature="agents.policy_checker", purpose="llm.judgment",
        system=('Review an HR policy draft. Reply JSON {"issues": [{"type": "gap"|"conflict"|"unclear"|"compliance", "detail", "suggestion"}], '
                '"summary"}. Only flag conflicts against the related policy excerpts given; do not invent laws.'),
        messages=[{"role": "user", "content": f"Draft '{title}':\n{text_body}\n\nRelated policies:\n" + "\n".join(f"- {h.document_title}: {h.text[:500]}" for h in related)}],
        input_refs={"entity_type": entity_type, "entity_id": str(entity_id) if entity_id else None},
    )
    return suggest(db, tenant, agent="policy_checker", kind="policy_review", title=f"Policy review: {title}", payload=review,
                   reviewer_permission="helpdesk.kb.edit", entity_type=entity_type, entity_id=entity_id, decision_log_id=log_id)


def suggestion_to_dict(s: AgentSuggestion) -> dict:
    return {"id": str(s.id), "agent": s.agent, "kind": s.kind, "title": s.title, "entity_type": s.entity_type,
            "entity_id": str(s.entity_id) if s.entity_id else None, "payload": s.payload_json, "status": s.status,
            "final_payload": s.final_payload_json, "reviewed_by": s.reviewed_by, "created_at": s.created_at.isoformat() if s.created_at else None}
