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
        if s.kind == "position_open_again":  # fix 2026-10-05: a to-do, not something to approve
            out.append({"kind": "todo", "id": str(s.id), "title": s.title,
                        "subtitle": f"{(s.payload_json or {}).get('person')} - {(s.payload_json or {}).get('why')}",
                        "due_at": None, "path": f"/jobs?view={(s.payload_json or {}).get('job_id')}", "actions": ["open"]})
            continue
        out.append({"kind": "ai_suggestion", "id": str(s.id), "title": s.title, "subtitle": f"{s.agent} suggestion -- review before it takes effect",
                    "due_at": None, "path": f"/approvals?suggestion={s.id}", "actions": ["approve", "edit", "reject"]})

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
