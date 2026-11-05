"""Unified Inbox (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 4; L-O1 "pending tasks &
approvals first"): one list of everything waiting on the caller, across modules --
workflow approvals (Part 5, each approvable from email via action tokens), AI agent
suggestions (Part 12), reviews to write (Part 10), onboarding tasks for their role
(Part 9) and clearance items they own (Part 11). Oldest-due first."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user import User
from app.platform.tenancy.context import TenantContext


def _iso(value):
    return value.isoformat() if value else None


def items_for(db: Session, tenant: TenantContext, user: User) -> list[dict]:
    from app.agents.service import inbox as agent_inbox
    from app.models.service_desk import CLEARANCE_OPEN, ClearanceItem
    from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep
    from app.platform.iam.org_scope import my_employee_id

    out: list[dict] = []
    steps = (
        db.query(WorkflowStep, WorkflowInstance, WorkflowDefinition)
        .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
        .filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.assignee_user_id == user.id, WorkflowStep.status == "pending")
        .all()
    )
    for step, instance, definition in steps:
        out.append({"kind": "approval", "id": str(step.id), "title": definition.name, "subtitle": instance.entity_type, "due_at": _iso(step.due_at),
                    "path": f"/approvals?step={step.id}", "actions": ["approve", "reject"]})

    for s in agent_inbox(db, tenant, user):
        if s.kind in ("employee_create", "it_mailbox_create", "it_mailbox_suspend"):  # Part 20.2: approval card / IT to-do on Employees
            out.append({"kind": "todo", "id": str(s.id), "title": s.title,
                        "subtitle": "approve to create the employee" if s.kind == "employee_create" else "IT: mailbox",
                        "due_at": None, "path": f"/employees?card={s.id}", "actions": ["open"]})
            continue
        if s.kind in ("interview_declined", "interview_reschedule", "interviewer_link"):  # Part 20.4
            pid = (s.payload_json or {}).get("interview_id")
            out.append({"kind": "todo", "id": str(s.id), "title": s.title,
                        "subtitle": "interviewer can't make it" if s.kind == "interview_declined" else ("new time asked" if s.kind == "interview_reschedule" else "interviewers"),
                        "due_at": None, "path": f"/interviews/dashboard?interview={pid}" if pid else "/interviews/interviewers", "actions": ["open"]})
            continue
        if s.kind == "interviews_reassign":  # Part 20.3: a leaver's future interviews
            out.append({"kind": "todo", "id": str(s.id), "title": s.title, "subtitle": "pick another interviewer for each",
                        "due_at": ((s.payload_json or {}).get("interviews") or [{}])[0].get("at"), "path": "/interviews", "actions": ["open"]})
            continue
        if s.kind == "position_open_again":  # fix 2026-10-05: a to-do, not something to approve
            out.append({"kind": "todo", "id": str(s.id), "title": s.title,
                        "subtitle": f"{(s.payload_json or {}).get('person')} - {(s.payload_json or {}).get('why')}",
                        "due_at": None, "path": f"/jobs?view={(s.payload_json or {}).get('job_id')}", "actions": ["open"]})
            continue
        if s.kind == "copilot_question":  # Part 22.1: the HR assistant handed a question to HR
            pl = s.payload_json or {}
            out.append({"kind": "copilot_question", "id": str(s.id), "title": s.title, "subtitle": pl.get("user_email") or "",
                        "due_at": None, "path": f"mailto:{pl.get('user_email', '')}?subject=Re: your question to the HR assistant", "actions": ["reply", "done"]})
            continue
        out.append({"kind": "ai_suggestion", "id": str(s.id), "title": s.title, "subtitle": f"{s.agent} suggestion -- review before it takes effect",
                    "due_at": None, "path": f"/approvals?suggestion={s.id}", "actions": ["approve", "edit", "reject"]})

    out += candidate_email_items(db, tenant, user)

    # Part 20.3: resignations waiting for this manager; profile change requests waiting for HR
    from app.employees import self_service
    from app.platform.iam.authz import has_permission

    for x in self_service.team_exits(db, tenant, user):
        out.append({"kind": "todo", "id": x["id"], "title": f"Approve the resignation of {x['employee_name']}", "subtitle": "your team - then HR confirms the last day",
                    "due_at": None, "path": f"/exits?approve={x['id']}", "actions": ["open"]})
    if has_permission(db, tenant, user, "core_hr.employee.edit"):
        for r in self_service.pending_requests(db, tenant):
            out.append({"kind": "todo", "id": r["id"], "title": f"Profile change: {r['employee_name']}", "subtitle": ", ".join(k.replace("_", " ") for k in r["changes"]),
                        "due_at": None, "path": f"/employees/{r['employee_id']}?change={r['id']}", "actions": ["open"]})

    me = my_employee_id(db, tenant, user)
    if me is not None:
        from app.models.performance import Review

        for review in db.query(Review).filter(Review.tenant_id == tenant.tenant_id, Review.reviewer_employee_id == me, Review.status != "submitted").all():
            out.append({"kind": "review", "id": str(review.id), "title": f"Write {review.stage} review", "subtitle": "performance review", "due_at": None,
                        "path": f"/settings#performance?review={review.id}", "actions": ["open"]})
    for item in db.query(ClearanceItem).filter(ClearanceItem.tenant_id == tenant.tenant_id, ClearanceItem.owner_user_id == user.id,
                                               ClearanceItem.status.in_(CLEARANCE_OPEN)).all():  # feat 2026-10-06: actionable exit checklist
        out.append({"kind": "clearance", "id": str(item.id), "title": item.title, "subtitle": f"exit checklist · {item.department}",
                    "due_at": datetime.combine(item.due_date, datetime.min.time(), tzinfo=timezone.utc).isoformat() if item.due_date else None,
                    "path": f"/exits?item={item.id}", "actions": ["open"]})

    far = datetime.max.replace(tzinfo=timezone.utc).isoformat()
    return sorted(out, key=lambda i: (i["due_at"] or far, i["kind"]))


CANDIDATE_EMAIL_ROLES = ("recruiter", "hiring_manager", "admin")  # who sees Candidate emails (ui_candidate_emails_router)


def candidate_email_items(db: Session, tenant: TenantContext, user: User, *, limit: int = 50) -> list[dict]:
    """Part 22.3: candidate emails in Needs action, as highlighted cards in My approvals (newest first).
    Marking done here or on Candidate emails is the same flag, so both lists agree."""
    if user.role not in CANDIDATE_EMAIL_ROLES:
        return []
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.hr_inbound_email import HrInboundEmail
    from app.models.job_role import JobRole
    from sqlalchemy import func

    rows = (db.query(HrInboundEmail).filter(HrInboundEmail.tenant_id == tenant.tenant_id, HrInboundEmail.status != "done")
            .order_by(func.coalesce(HrInboundEmail.received_at, HrInboundEmail.created_at).desc()).limit(limit).all())
    out = []
    for r in rows:
        cand = db.get(Candidate, r.matched_candidate_id) if r.matched_candidate_id else None
        app = db.get(Application, r.matched_application_id) if r.matched_application_id else None
        job = db.get(JobRole, app.job_role_id) if app else None
        out.append({
            "kind": "candidate_email", "id": str(r.id), "title": cand.full_name if cand else (r.from_name or r.from_address),
            "subtitle": job.title if job else (r.from_address if cand else "not linked yet"),
            "summary": r.summary or r.subject, "received_at": _iso(r.received_at or r.created_at), "unread": r.read_at is None,
            "linked": cand is not None, "from_address": r.from_address, "due_at": None,
            "path": f"/candidate-emails?email={r.id}", "actions": ["open", "reply", "link", "done"],
        })
    return out


def count_for(db: Session, tenant: TenantContext, user: User) -> dict:
    """Part 22.3: the My approvals badge -- workflow approvals + everything items_for() lists (candidate emails included)."""
    from app.models.workflow import WorkflowStep

    approvals = db.query(WorkflowStep).filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.assignee_user_id == user.id,
                                              WorkflowStep.status == "pending").count()
    items = items_for(db, tenant, user)
    others = [i for i in items if i["kind"] != "approval"]
    return {"total": approvals + len(others), "candidate_emails": sum(1 for i in others if i["kind"] == "candidate_email"),
            "unread_emails": sum(1 for i in others if i["kind"] == "candidate_email" and i.get("unread"))}
