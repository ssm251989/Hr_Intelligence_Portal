"""Copilot personal-data tools (docs/HRMS_COMPLETE_SPEC.txt Part 12 B): "my interview
schedule", "my assets", "status of my ticket", "who approves my request". Each tool
declares the permission it needs and ALWAYS answers about the caller only -- it goes
through the normal service layer (never a raw query built from chat text), and a caller
without the permission gets a refusal, not data.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.interview import Interview
from app.models.service_desk import Ticket
from app.models.user import User
from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep
from app.platform.iam.authz import has_permission
from app.platform.iam.org_scope import my_employee_id
from app.platform.tenancy.context import TenantContext


class ToolPermissionError(PermissionError):
    pass


@dataclass
class ToolDef:
    name: str
    permission: Optional[str]  # None = any signed-in user
    triggers: tuple[str, ...]  # lower-case phrases (en/hi/ta) that route a question here
    run: Callable[[Session, TenantContext, User], dict]


def _my_interviews(db: Session, tenant: TenantContext, user: User) -> dict:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Interview)
        .filter(Interview.tenant_id == tenant.tenant_id, Interview.scheduled_at >= now)
        .filter((Interview.interviewer_id == user.id) | (Interview.interviewer_email == user.email))
        .order_by(Interview.scheduled_at.asc()).limit(10).all()
    )
    return {"interviews": [{"scheduled_at": r.scheduled_at.isoformat(), "meeting_link": r.meeting_link} for r in rows]}


def _my_assets(db: Session, tenant: TenantContext, user: User) -> dict:
    from app.models.service_desk import Asset
    from app.service_desk import assets

    me = my_employee_id(db, tenant, user)
    if me is None:
        return {"assets": []}
    return {"assets": [{"name": db.get(Asset, a.asset_id).name, "tag": db.get(Asset, a.asset_id).asset_tag, "since": a.allocated_at.isoformat() if a.allocated_at else None}
                       for a in assets.employee_assets(db, tenant, me)]}


def _my_tickets(db: Session, tenant: TenantContext, user: User) -> dict:
    rows = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.requester_user_id == user.id).order_by(Ticket.created_at.desc()).limit(5).all()
    return {"tickets": [{"number": t.number, "subject": t.subject, "status": t.status} for t in rows]}


def _who_approves(db: Session, tenant: TenantContext, user: User) -> dict:
    instances = db.query(WorkflowInstance).filter(WorkflowInstance.tenant_id == tenant.tenant_id, WorkflowInstance.status == "running").all()
    mine = [i for i in instances if (i.context_json or {}).get("started_by_user_id") == str(user.id)]
    out = []
    for instance in mine[:5]:
        definition = db.get(WorkflowDefinition, instance.definition_id)
        pending = db.query(WorkflowStep).filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").all()
        approvers = []
        for step in pending:
            approver = db.get(User, step.assignee_user_id) if step.assignee_user_id else None
            approvers.append(approver.full_name or approver.email if approver else "unassigned")
        out.append({"request": definition.name if definition else instance.entity_type, "waiting_on": approvers})
    return {"requests": out}


TOOLS: dict[str, ToolDef] = {t.name: t for t in (
    ToolDef("my_interviews", "recruitment.interview.view", ("my interview", "interview schedule", "मेरा इंटरव्यू", "நேர்காணல்"), _my_interviews),
    ToolDef("my_assets", "assets.self.view", ("my asset", "my laptop", "assets assigned", "मेरी संपत्ति", "என் சொத்து"), _my_assets),
    ToolDef("my_tickets", "helpdesk.self.view", ("my ticket", "ticket status", "status of my", "मेरा टिकट", "என் டிக்கெட்"), _my_tickets),
    ToolDef("who_approves", None, ("who approves", "who will approve", "pending approval", "कौन मंजूरी", "யார் ஒப்புதல்"), _who_approves),
)}


def match_tool(question: str) -> Optional[ToolDef]:
    lowered = question.lower()
    for tool in TOOLS.values():
        if any(trigger in lowered for trigger in tool.triggers):
            return tool
    return None


def run_tool(db: Session, tenant: TenantContext, user: User, tool: ToolDef) -> dict:
    if tool.permission and not has_permission(db, tenant, user, tool.permission):
        raise ToolPermissionError(tool.permission)
    return tool.run(db, tenant, user)
