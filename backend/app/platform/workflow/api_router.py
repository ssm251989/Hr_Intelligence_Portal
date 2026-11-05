"""Workflow & Approval Engine API (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 3-4) --
scoped down the same way every other part's admin surface has been (see docs/build_log.md's
own Part 5 note): definition CRUD + publish + simulate (dry-run, no live React Flow
drag-drop canvas -- a JSON graph editor is the scoped-down equivalent, same class of
reduction as Part 4's plain-list template editor standing in for a split-view live-preview
one), instance list/get, the Unified Inbox (GET /api/v1/inbox), act-on-step
(approve/reject/send-back/skip), and action-token-based one-click approve/reject from an
email link (reusing platform.iam.action_tokens -- the exact mechanism section 3 names).
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep
from app.platform.iam.action_tokens import ActionTokenError, create_action_token, mark_action_token_responded, resolve_action_token
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant, tenant_context
from app.platform.workflow import definitions, engine

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])
inbox_router = APIRouter(prefix="/api/v1", tags=["workflow"])
public_router = APIRouter(prefix="/api/v1/public/workflow", tags=["workflow-public"])


# ---- definitions ----


class DefinitionCreate(BaseModel):
    key: str
    name: str
    module: Optional[str] = None
    trigger: dict = {}
    graph: dict


class DefinitionRead(BaseModel):
    id: UUID
    key: str
    name: str
    module: Optional[str]
    version: int
    status: str
    trigger_json: dict
    graph_json: dict
    published_at: Optional[datetime]


def _definition_read(d: WorkflowDefinition) -> DefinitionRead:
    return DefinitionRead(id=d.id, key=d.key, name=d.name, module=d.module, version=d.version, status=d.status, trigger_json=d.trigger_json or {}, graph_json=d.graph_json or {}, published_at=d.published_at)


@router.get("/definitions", response_model=list[DefinitionRead])
def list_definitions(db: Session = Depends(get_db), current_user: User = Depends(require("workflow.definitions.view"))):
    from sqlalchemy import func

    tenant = require_current_tenant()
    latest_versions = (
        db.query(WorkflowDefinition.key, func.max(WorkflowDefinition.version).label("v"))
        .filter(WorkflowDefinition.tenant_id == tenant.tenant_id)
        .group_by(WorkflowDefinition.key)
        .subquery()
    )
    rows = (
        db.query(WorkflowDefinition)
        .join(latest_versions, (WorkflowDefinition.key == latest_versions.c.key) & (WorkflowDefinition.version == latest_versions.c.v))
        .filter(WorkflowDefinition.tenant_id == tenant.tenant_id)
        .order_by(WorkflowDefinition.key)
        .all()
    )
    return [_definition_read(d) for d in rows]


@router.post("/definitions", response_model=DefinitionRead, status_code=201)
def create_definition(payload: DefinitionCreate, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.definitions.configure"))):
    tenant = require_current_tenant()
    definition = definitions.create_draft(db, tenant.tenant_id, key=payload.key, name=payload.name, module=payload.module, trigger=payload.trigger, graph=payload.graph)
    return _definition_read(definition)


@router.post("/definitions/{definition_id}/publish", response_model=DefinitionRead)
def publish_definition(definition_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.definitions.configure"))):
    definition = db.get(WorkflowDefinition, definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition not found")
    try:
        definition = definitions.publish(db, definition, actor=current_user.email)
    except definitions.DefinitionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _definition_read(definition)


class SimulateRequest(BaseModel):
    sample_context: dict[str, Any] = {}


@router.post("/definitions/{definition_id}/simulate")
def simulate_definition(definition_id: UUID, payload: SimulateRequest, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.definitions.view"))):
    definition = db.get(WorkflowDefinition, definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition not found")
    try:
        return {"path": engine.simulate(definition, payload.sample_context)}
    except engine.WorkflowConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---- instances ----


class StepRead(BaseModel):
    id: UUID
    node_id: str
    node_type: str
    status: str
    assignee_user_id: Optional[UUID]
    due_at: Optional[datetime]
    acted_by: Optional[str]
    action: Optional[str]
    comment: Optional[str]


def _step_read(s: WorkflowStep) -> StepRead:
    return StepRead(id=s.id, node_id=s.node_id, node_type=s.node_type, status=s.status, assignee_user_id=s.assignee_user_id, due_at=s.due_at, acted_by=s.acted_by, action=s.action, comment=s.comment)


class InstanceRead(BaseModel):
    id: UUID
    definition_id: UUID
    definition_version: int
    entity_type: str
    entity_id: UUID
    status: str
    current_node_id: Optional[str]
    started_by: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    steps: list[StepRead]


def _instance_read(db: Session, i: WorkflowInstance) -> InstanceRead:
    steps = db.query(WorkflowStep).filter(WorkflowStep.instance_id == i.id).order_by(WorkflowStep.started_at).all()
    return InstanceRead(
        id=i.id, definition_id=i.definition_id, definition_version=i.definition_version, entity_type=i.entity_type,
        entity_id=i.entity_id, status=i.status, current_node_id=i.current_node_id, started_by=i.started_by,
        started_at=i.started_at, ended_at=i.ended_at, steps=[_step_read(s) for s in steps],
    )


@router.get("/instances", response_model=list[InstanceRead])
def list_instances(
    entity_type: Optional[str] = None, status: Optional[str] = None,
    db: Session = Depends(get_db), current_user: User = Depends(require("workflow.instances.view")),
):
    tenant = require_current_tenant()
    query = db.query(WorkflowInstance).filter(WorkflowInstance.tenant_id == tenant.tenant_id)
    if entity_type is not None:
        query = query.filter(WorkflowInstance.entity_type == entity_type)
    if status is not None:
        query = query.filter(WorkflowInstance.status == status)
    return [_instance_read(db, i) for i in query.order_by(WorkflowInstance.started_at.desc()).limit(100).all()]


@router.get("/instances/{instance_id}", response_model=InstanceRead)
def get_instance(instance_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.instances.view"))):
    instance = db.get(WorkflowInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return _instance_read(db, instance)


# ---- act on a step (approve/reject/send-back/skip) ----


class StepActionRequest(BaseModel):
    action: str
    comment: Optional[str] = None


@router.post("/steps/{step_id}/act", response_model=StepRead)
def act_on_step(step_id: UUID, payload: StepActionRequest, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.instances.approve"))):
    tenant = require_current_tenant()
    try:
        step = engine.act_on_step(db, tenant, step_id, actor=current_user.email, action=payload.action, comment=payload.comment)
    except engine.WorkflowStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except engine.WorkflowConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _step_read(step)


@router.post("/steps/{step_id}/action-link", response_model=dict)
def create_step_action_link(step_id: UUID, action: str, db: Session = Depends(get_db), current_user: User = Depends(require("workflow.instances.approve"))):
    """Mints the signed one-time link section 3's Unified Inbox uses for "approve/reject
    from email" -- `action` names which verb this specific link commits to (so the email
    can offer separate Approve/Reject buttons, each its own link)."""
    tenant = require_current_tenant()
    step = db.get(WorkflowStep, step_id)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")
    token_row = create_action_token(db, tenant, entity_type="workflow_step", entity_id=step_id, action=action, created_by=current_user.email)
    return {"token": token_row.token}


# ---- unified inbox ----


class InboxRow(BaseModel):
    step_id: UUID
    instance_id: UUID
    entity_type: str
    entity_id: UUID
    node_id: str
    due_at: Optional[datetime]
    definition_name: str


@inbox_router.get("/inbox", response_model=list[InboxRow])
def unified_inbox(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Every pending approval/task assigned to the caller, across every module -- real
    and module-agnostic since it's all one workflow_steps table (section 3's own point)."""
    tenant = require_current_tenant()
    steps = (
        db.query(WorkflowStep)
        .filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.assignee_user_id == current_user.id, WorkflowStep.status == "pending")
        .order_by(WorkflowStep.due_at.asc().nulls_last())
        .all()
    )
    rows = []
    for step in steps:
        instance = db.get(WorkflowInstance, step.instance_id)
        definition = db.get(WorkflowDefinition, instance.definition_id)
        rows.append(InboxRow(step_id=step.id, instance_id=instance.id, entity_type=instance.entity_type, entity_id=instance.entity_id, node_id=step.node_id, due_at=step.due_at, definition_name=definition.name))
    return rows


# ---- action-token-based one-click approve/reject page (public, no-auth -- same "exact
# link from an email" pattern as confirm_router.py/negotiation_router.py) ----


def _render_action_result_page(heading: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{heading}</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #eef1f6;
            margin: 0; padding: 0; color: #1a1a1a; }}
    .card {{ max-width: 480px; margin: 64px auto; background: #ffffff; border-radius: 12px;
             padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center; }}
    h1 {{ font-size: 22px; margin-bottom: 12px; }}
    p {{ font-size: 15px; line-height: 1.5; color: #333333; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{heading}</h1>
    <p>{message}</p>
  </div>
</body>
</html>
"""


@public_router.get("/action/{token}", response_class=HTMLResponse)
def resolve_action_link(token: str, db: Session = Depends(get_db)):
    """Decodes the token to find its own tenant (action_tokens are TenantOwned like
    everything else -- the token string itself, not a header/host, is what identifies
    which tenant to look in, same reasoning as Part 4's preferences page)."""
    from app.models.iam import ActionToken

    row = db.query(ActionToken).filter(ActionToken.token == token).first()
    if row is None:
        return HTMLResponse(_render_action_result_page("Link not recognized", "This link isn't valid. Please use the exact link from your email."))

    with tenant_context(row.tenant_id):
        tenant = require_current_tenant()
        try:
            action_token = resolve_action_token(db, tenant, token)
        except ActionTokenError as reason:
            messages = {
                "expired": "This link has expired.",
                "already_handled": "This has already been handled -- if you didn't do this yourself, please check with your team.",
            }
            return HTMLResponse(_render_action_result_page("Link no longer valid", messages.get(str(reason), "This link is no longer valid.")))

        step = db.get(WorkflowStep, action_token.entity_id)
        if step is None or step.status != "pending":
            return HTMLResponse(_render_action_result_page("Already handled", "This step has already been resolved."))

        try:
            engine.act_on_step(db, tenant, step.id, actor=action_token.created_by or "email-link", action=action_token.action, comment=(action_token.payload_json or {}).get("comment"))
        except (engine.WorkflowStateError, engine.WorkflowConfigError) as exc:
            return HTMLResponse(_render_action_result_page("Could not process", str(exc)))

        mark_action_token_responded(db, action_token)

    verb = {"approve": "approved", "reject": "rejected", "send_back": "sent back"}.get(action_token.action, "recorded")
    return HTMLResponse(_render_action_result_page("Thanks!", f"Your response ({verb}) has been recorded."))
