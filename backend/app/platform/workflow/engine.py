"""Workflow & Approval Engine runtime (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 2).

graph_json shape (a definition's own DATA, not code):
  {"start_node": "n1", "nodes": {"n1": {"type": "condition", ...}, ...}}

Node `type`s and what's REAL here vs. deliberately scoped down (see docs/build_log.md's
own Part 5 note for the full reasoning on each):
  condition/switch  -- real, synchronous (JSONLogic against the instance's context_json).
  approval          -- real. `approvers` is a list of resolver specs (platform.workflow.
                       resolvers.resolve); `mode` is "sequential" (specs act as ordered
                       GATES, each gate's own resolved users race for a single quorum=1
                       "any one of them" win before the next gate opens) or "parallel"/
                       "any"/"quorum" (every spec's users resolved into ONE pool up front,
                       a single quorum threshold applied across the whole pool -- parallel
                       = quorum equals pool size, any = quorum 1). `auto_approve_condition`
                       (JSONLogic) skips straight past a real human step when it matches.
  task              -- real, same single-pool/quorum=1 mechanics as an approval node's
                       pool, just without approve/reject semantics (task action is
                       "complete").
  action            -- real for set_field/create_record (against context_json only, not
                       live ORM rows -- see this module's own note below), send_
                       notification (Part 4's comms.send), call_connector (Part 3's
                       ConnectorRouter directly), webhook (Part 3's generic_webhook
                       provider). generate_document is a documented stub (no generic
                       document-generation service exists yet).
  wait              -- real creation of a workflow_timers row; NOT auto-flushed (no live
                       Celery beat -- same gap as Part 2's TenantTask/Part 4's quiet-hours
                       holds). process_due_timers() below is real and directly testable.
  parallel          -- scoped down to branches of non-pausing node chains only (condition/
                       switch/action) executed synchronously, then continuing to `next`.
                       A branch that reaches a pausing node (approval/task/wait/
                       sub_workflow) raises WorkflowConfigError -- true concurrent PAUSED
                       branches need per-branch cursor tracking this instance's single
                       `current_node_id` column doesn't have room for; not attempted.
  sub_workflow      -- starts a child instance and continues the parent immediately
                       (fire-and-forget) -- a genuinely BLOCKING sub-workflow call needs
                       the same missing capability parallel/join does.
  end               -- terminal; sets instance.status from `outcome`.

`set_field`/`create_record` operate on `instance.context_json` only, never a live ORM row
on an arbitrary model -- doing that generically and safely needs Part 6's metadata/custom-
field registry (which model, which field, what type-validates it) that doesn't exist yet.
A real caller wanting a workflow to actually mutate a business record does so from its own
`action`/`send_notification` step's own module-specific code reading the completed
instance's context_json, the same way `interview_scheduling/negotiation.py` already reads
its own state machine's data -- not something this generic engine does for you yet.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep, WorkflowTimer
from app.platform.tenancy.context import TenantContext
from app.platform.workflow.resolvers import ResolverNotSupportedError, auto_approve_condition_met, resolve as resolve_approvers

_PAUSING_NODE_TYPES = {"approval", "task", "wait", "sub_workflow"}
_QUORUM_NODE_TYPES = {"approval", "task"}


class WorkflowConfigError(Exception):
    pass


class WorkflowStateError(Exception):
    pass


def _node(definition: WorkflowDefinition, node_id: str) -> dict:
    node = (definition.graph_json or {}).get("nodes", {}).get(node_id)
    if node is None:
        raise WorkflowConfigError(f"Workflow {definition.key!r} has no node {node_id!r}")
    return node


def start_instance(
    db: Session, tenant: TenantContext, definition: WorkflowDefinition, *, entity_type: str, entity_id: UUID,
    context: dict, started_by: Optional[str] = None, started_by_user_id: Optional[UUID] = None,
) -> WorkflowInstance:
    full_context = {**context, "started_by_user_id": str(started_by_user_id) if started_by_user_id else None}
    instance = WorkflowInstance(
        tenant_id=tenant.tenant_id, definition_id=definition.id, definition_version=definition.version,
        entity_type=entity_type, entity_id=entity_id, status="running", context_json=full_context,
        current_node_id=definition.graph_json.get("start_node"), started_by=started_by,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    _advance(db, tenant, definition, instance, instance.current_node_id)
    return instance


def _end_instance(db: Session, instance: WorkflowInstance, outcome: str) -> None:
    instance.status = {"approved": "completed", "rejected": "cancelled"}.get(outcome, "completed")
    instance.current_node_id = None
    instance.ended_at = datetime.now(timezone.utc)
    instance.context_json = {**instance.context_json, "outcome": outcome}
    db.commit()


def _advance(db: Session, tenant: TenantContext, definition: WorkflowDefinition, instance: WorkflowInstance, node_id: str) -> None:
    """Walks forward through synchronous nodes (condition/switch/action/parallel/
    sub_workflow) until it hits a pausing node (sets current_node_id, returns) or an end
    node (ends the instance, returns)."""
    while True:
        node = _node(definition, node_id)
        node_type = node["type"]

        if node_type == "end":
            _end_instance(db, instance, node.get("outcome", "approved"))
            return

        if node_type == "condition":
            from json_logic import jsonLogic

            node_id = node["on_true"] if jsonLogic(node["jsonlogic"], instance.context_json) else node["on_false"]
            continue

        if node_type == "switch":
            from json_logic import jsonLogic

            matched = next((case["next"] for case in node.get("cases", []) if jsonLogic(case["jsonlogic"], instance.context_json)), None)
            node_id = matched or node["default"]
            continue

        if node_type == "action":
            _run_action(db, tenant, instance, node)
            node_id = node["next"]
            continue

        if node_type == "parallel":
            for branch_start in node["branches"]:
                _run_non_pausing_branch(db, tenant, definition, instance, branch_start)
            node_id = node["next"]
            continue

        if node_type == "sub_workflow":
            from app.platform.workflow.definitions import get_published_definition

            child_definition = get_published_definition(db, tenant.tenant_id, node["definition_key"])
            start_instance(db, tenant, child_definition, entity_type=instance.entity_type, entity_id=instance.entity_id, context=dict(instance.context_json), started_by=instance.started_by)
            node_id = node["next"]
            continue

        if node_type in _PAUSING_NODE_TYPES:
            instance.current_node_id = node_id
            db.commit()
            try:
                if node_type in _QUORUM_NODE_TYPES:
                    _enter_quorum_node(db, tenant, instance, node_id, node)
                elif node_type == "wait":
                    _enter_wait_node(db, instance, node_id, node)
            except WorkflowConfigError:
                # Section 2's own "no half-done state": a misconfigured node (e.g. zero
                # resolved approvers) must not leave the instance stuck "running" forever
                # with no step anyone could ever act on -- fail it visibly instead.
                instance.status = "failed"
                instance.ended_at = datetime.now(timezone.utc)
                db.commit()
                raise
            return

        raise WorkflowConfigError(f"Unknown node type: {node_type!r}")


def _run_non_pausing_branch(db: Session, tenant: TenantContext, definition: WorkflowDefinition, instance: WorkflowInstance, node_id: str) -> None:
    """A `parallel` branch -- must terminate at an `end`-reachable chain of condition/
    switch/action nodes only; hitting a pausing node here is the documented parallel/join
    scope limit (see this module's own docstring)."""
    while True:
        node = _node(definition, node_id)
        node_type = node["type"]
        if node_type == "action":
            _run_action(db, tenant, instance, node)
            node_id = node["next"]
            continue
        if node_type == "condition":
            from json_logic import jsonLogic

            node_id = node["on_true"] if jsonLogic(node["jsonlogic"], instance.context_json) else node["on_false"]
            continue
        if node_type == "switch":
            from json_logic import jsonLogic

            matched = next((case["next"] for case in node.get("cases", []) if jsonLogic(case["jsonlogic"], instance.context_json)), None)
            node_id = matched or node["default"]
            continue
        if node_type == "branch_end":
            return
        raise WorkflowConfigError(f"parallel branch hit a pausing node type {node_type!r} -- concurrent paused branches aren't supported yet (see engine.py's own docstring).")


def _resolve_pool(db: Session, tenant: TenantContext, node: dict, context: dict) -> set[UUID]:
    pool: set[UUID] = set()
    for spec in node["approvers"]:
        pool |= resolve_approvers(db, tenant, spec, context)
    return pool


def _quorum_for(node: dict, pool_size: int) -> int:
    mode = node.get("mode", "quorum")
    if mode == "parallel":
        return pool_size
    if mode == "any":
        return 1
    if mode == "quorum":
        return int(node["quorum"])
    raise WorkflowConfigError(f"Unknown approval mode: {mode!r} (sequential is handled separately)")


def _enter_quorum_node(db: Session, tenant: TenantContext, instance: WorkflowInstance, node_id: str, node: dict) -> None:
    if node.get("mode") == "sequential":
        _enter_sequential_gate(db, tenant, instance, node_id, node, gate_index=0)
        return

    if auto_approve_condition_met(node, instance.context_json):
        db.add(WorkflowStep(
            tenant_id=tenant.tenant_id, instance_id=instance.id, node_id=node_id, node_type=node["type"],
            status="approved", acted_by="system:auto-approve", action="approve", ended_at=datetime.now(timezone.utc),
        ))
        db.commit()
        definition = db.get(WorkflowDefinition, instance.definition_id)
        _advance(db, tenant, definition, instance, node["on_approve"])
        return

    pool = _resolve_pool(db, tenant, node, instance.context_json)
    if not pool:
        raise WorkflowConfigError(f"Node {node_id!r} resolved zero approvers/assignees -- misconfigured workflow_definition")
    quorum = _quorum_for(node, len(pool)) if node["type"] == "approval" else 1
    for user_id in pool:
        db.add(WorkflowStep(
            tenant_id=tenant.tenant_id, instance_id=instance.id, node_id=node_id, node_type=node["type"],
            status="pending", assignee_user_id=user_id, due_at=_due_at(node),
            payload_json={"quorum": quorum, "pool_size": len(pool)},
        ))
    db.commit()
    _create_sla_timer(db, tenant, instance, node_id, node)


def _enter_sequential_gate(db: Session, tenant: TenantContext, instance: WorkflowInstance, node_id: str, node: dict, *, gate_index: int) -> None:
    gates = node["approvers"]
    if gate_index >= len(gates):
        definition = db.get(WorkflowDefinition, instance.definition_id)
        _advance(db, tenant, definition, instance, node["on_approve"])
        return
    gate_pool = resolve_approvers(db, tenant, gates[gate_index], instance.context_json)
    if not gate_pool:
        raise WorkflowConfigError(f"Node {node_id!r} gate {gate_index} resolved zero approvers -- misconfigured workflow_definition")
    for user_id in gate_pool:
        db.add(WorkflowStep(
            tenant_id=tenant.tenant_id, instance_id=instance.id, node_id=node_id, node_type=node["type"],
            status="pending", assignee_user_id=user_id, due_at=_due_at(node),
            payload_json={"gate_index": gate_index, "quorum": 1, "pool_size": len(gate_pool)},
        ))
    db.commit()
    _create_sla_timer(db, tenant, instance, node_id, node)


def _due_at(node: dict) -> Optional[datetime]:
    due_hours = node.get("due_hours") or node.get("sla_hours")
    return datetime.now(timezone.utc) + timedelta(hours=due_hours) if due_hours else None


def _create_sla_timer(db: Session, tenant: TenantContext, instance: WorkflowInstance, node_id: str, node: dict) -> None:
    sla_hours = node.get("sla_hours")
    if not sla_hours:
        return
    db.add(WorkflowTimer(
        tenant_id=tenant.tenant_id, instance_id=instance.id, kind="sla_escalation",
        fires_at=datetime.now(timezone.utc) + timedelta(hours=sla_hours), payload_json={"node_id": node_id},
    ))
    db.commit()


def _enter_wait_node(db: Session, instance: WorkflowInstance, node_id: str, node: dict) -> None:
    if "duration_hours" in node:
        fires_at = datetime.now(timezone.utc) + timedelta(hours=node["duration_hours"])
    elif "until_date_context_key" in node:
        fires_at = datetime.fromisoformat(instance.context_json[node["until_date_context_key"]])
    else:
        raise WorkflowConfigError(f"wait node {node_id!r} needs duration_hours or until_date_context_key")
    db.add(WorkflowTimer(tenant_id=instance.tenant_id, instance_id=instance.id, kind="wait", fires_at=fires_at, payload_json={"node_id": node_id, "next": node["next"]}))
    db.commit()


# ---- acting on a pending step ----


ACTIONS = ("approve", "reject", "complete", "send_back", "skip")


def act_on_step(db: Session, tenant: TenantContext, step_id: UUID, *, actor: str, action: str, comment: Optional[str] = None) -> WorkflowStep:
    if action not in ACTIONS:
        raise WorkflowConfigError(f"Unknown step action: {action!r}")
    step = db.get(WorkflowStep, step_id)
    if step is None or step.tenant_id != tenant.tenant_id:
        raise WorkflowStateError("Step not found")
    if step.status != "pending":
        raise WorkflowStateError(f"Step is already {step.status!r}")

    instance = db.get(WorkflowInstance, step.instance_id)
    definition = db.get(WorkflowDefinition, instance.definition_id)
    node = _node(definition, step.node_id)

    if action == "reject" and node.get("comments_required_on_reject") and not comment:
        raise WorkflowConfigError("This node requires a comment when rejecting")
    if action == "send_back" and not node.get("allow_send_back"):
        raise WorkflowConfigError("This node does not allow send-back")

    step.status = {"approve": "approved", "reject": "rejected", "complete": "approved", "send_back": "sent_back", "skip": "skipped"}[action]
    step.acted_by = actor
    step.action = action
    step.comment = comment
    step.ended_at = datetime.now(timezone.utc)
    db.commit()

    _evaluate_node_progress(db, tenant, definition, instance, step, node)
    return step


def _evaluate_node_progress(db: Session, tenant: TenantContext, definition: WorkflowDefinition, instance: WorkflowInstance, acted_step: WorkflowStep, node: dict) -> None:
    node_id = acted_step.node_id
    if instance.current_node_id != node_id or instance.status != "running":
        return  # already resolved by an earlier concurrent step

    # Sequential mode's "live" siblings are the ones sharing acted_step's OWN gate_index
    # -- derived from the step actually acted on, never from siblings' query-return
    # order (SQL gives no ordering guarantee without an explicit ORDER BY, and a stale
    # gate from BEFORE this one advanced would otherwise sometimes win by accident).
    siblings = db.query(WorkflowStep).filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.instance_id == instance.id, WorkflowStep.node_id == node_id).all()
    acted_gate = acted_step.payload_json.get("gate_index") if acted_step.payload_json else None
    live = [s for s in siblings if s.payload_json and (node.get("mode") != "sequential" or s.payload_json.get("gate_index") == acted_gate)]
    quorum = live[0].payload_json.get("quorum", 1) if live else 1
    approved = sum(1 for s in live if s.status == "approved")
    rejected = sum(1 for s in live if s.status == "rejected")
    sent_back = [s for s in live if s.status == "sent_back"]
    pool_size = live[0].payload_json.get("pool_size", len(live)) if live else len(live)

    if sent_back:
        _supersede_pending(db, tenant, instance, node_id, live)
        _advance(db, tenant, definition, instance, node.get("on_send_back") or node["on_reject"])
        return

    if approved >= quorum:
        _supersede_pending(db, tenant, instance, node_id, live)
        if node.get("mode") == "sequential":
            _enter_sequential_gate(db, tenant, instance, node_id, node, gate_index=live[0].payload_json["gate_index"] + 1)
        else:
            _advance(db, tenant, definition, instance, node["on_approve"])
        return

    if rejected > pool_size - quorum:
        _supersede_pending(db, tenant, instance, node_id, live)
        _advance(db, tenant, definition, instance, node["on_reject"])
        return
    # else: still waiting on more responses -- instance stays paused on this node.


def _supersede_pending(db: Session, tenant: TenantContext, instance: WorkflowInstance, node_id: str, steps: list[WorkflowStep]) -> None:
    from app.platform.iam.action_tokens import invalidate_action_tokens_for

    for step in steps:
        if step.status == "pending":
            step.status = "skipped"
            step.ended_at = datetime.now(timezone.utc)
        invalidate_action_tokens_for(db, tenant, entity_type="workflow_step", entity_id=step.id)
    db.commit()


# ---- actions ----


def _run_action(db: Session, tenant: TenantContext, instance: WorkflowInstance, node: dict) -> None:
    action = node["action"]
    params = node.get("params", {})

    if action == "set_field":
        instance.context_json = {**instance.context_json, params["field"]: _resolve_param_value(params["value"], instance.context_json)}
        db.commit()
        return

    if action == "create_record":
        records = instance.context_json.get("_created_records", [])
        records.append({"type": params["record_type"], "data": {k: _resolve_param_value(v, instance.context_json) for k, v in params.get("data", {}).items()}})
        instance.context_json = {**instance.context_json, "_created_records": records}
        db.commit()
        return

    if action == "send_notification":
        from app.platform.comms.service import send

        to = params.get("to") or [instance.context_json[params["to_context_key"]]]
        send(db, tenant, template_key=params["template_key"], to=to, ctx=instance.context_json, purpose=params.get("purpose", "email.outbound.default"))
        return

    if action == "call_connector":
        from app.platform.connectors.router import ConnectorRouter

        resolved = ConnectorRouter(db).resolve(params["purpose"], instance.context_json)
        instance.context_json = {**instance.context_json, "_last_connector_resolved": resolved.connection.id and str(resolved.connection.id)}
        db.commit()
        return

    if action == "webhook":
        from app.platform.connectors.providers.generic_webhook import GenericWebhookAdapter

        adapter = GenericWebhookAdapter(params.get("config", {}), {})
        result = adapter.send(params["url"], instance.context_json, params.get("secret", ""))
        instance.context_json = {**instance.context_json, "_webhook_sent": result.success}
        db.commit()
        return

    if action == "run_ai":
        from app.platform.ai.gateway import complete

        result = complete(
            db, tenant, purpose=params.get("purpose", "llm.copilot"),
            system=params.get("system", ""), messages=[{"role": "user", "content": params["prompt"]}],
        )
        instance.context_json = {**instance.context_json, "_ai_result": result}
        db.commit()
        return

    if action == "generate_document":
        raise WorkflowConfigError("generate_document is not implemented yet -- no generic document-generation service exists (see engine.py's own docstring)")

    raise WorkflowConfigError(f"Unknown action type: {action!r}")


def _resolve_param_value(value: Any, context: dict) -> Any:
    if isinstance(value, dict) and "jsonlogic" in value:
        from json_logic import jsonLogic

        return jsonLogic(value["jsonlogic"], context)
    return value


# ---- timers (documented Celery-beat gap -- process_due_timers is real, just not
# scheduled; see this module's own docstring) ----


def process_due_timers(db: Session, tenant: TenantContext, *, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    due = (
        db.query(WorkflowTimer)
        .filter(WorkflowTimer.tenant_id == tenant.tenant_id, WorkflowTimer.processed_at.is_(None), WorkflowTimer.fires_at <= now)
        .all()
    )
    processed = 0
    for timer in due:
        instance = db.get(WorkflowInstance, timer.instance_id)
        if instance is None or instance.status != "running":
            timer.processed_at = now
            continue
        definition = db.get(WorkflowDefinition, instance.definition_id)
        if timer.kind == "wait" and instance.current_node_id == timer.payload_json.get("node_id"):
            timer.processed_at = now
            db.commit()
            _advance(db, tenant, definition, instance, timer.payload_json["next"])
            processed += 1
        elif timer.kind == "sla_escalation":
            timer.processed_at = now
            db.commit()
            # Escalation itself (reassign to the resolver's own escalation target) needs
            # the same org-hierarchy resolvers this build doesn't have yet -- the timer is
            # correctly recorded as fired/processed, not silently skipped, but no
            # reassignment action runs. See docs/build_log.md's own Part 5 note.
            processed += 1
        else:
            timer.processed_at = now
            processed += 1
    db.commit()
    return processed


# ---- simulation (section 4's own "simulate with a sample record" -- pure backend logic,
# no React Flow canvas needed for this part) ----


def simulate(definition: WorkflowDefinition, sample_context: dict) -> list[dict]:
    """Walks the graph with the SAME logic _advance uses, but never touches the DB or
    creates real steps -- returns the path taken (list of {"node_id", "type", ...}) plus,
    for each approval/task node reached, which approvers WOULD be notified (as resolver
    specs, not resolved user_ids -- resolving needs a live DB/tenant this pure function
    deliberately doesn't take, so a caller wanting resolved names calls resolvers.resolve()
    itself per node in the returned path)."""
    path: list[dict] = []
    node_id = definition.graph_json.get("start_node")
    context = dict(sample_context)
    seen = set()
    while node_id not in seen:
        seen.add(node_id)
        node = _node(definition, node_id)
        entry = {"node_id": node_id, "type": node["type"]}
        path.append(entry)

        if node["type"] == "end":
            break
        if node["type"] == "condition":
            from json_logic import jsonLogic

            node_id = node["on_true"] if jsonLogic(node["jsonlogic"], context) else node["on_false"]
        elif node["type"] == "switch":
            from json_logic import jsonLogic

            node_id = next((c["next"] for c in node.get("cases", []) if jsonLogic(c["jsonlogic"], context)), node["default"])
        elif node["type"] == "action":
            node_id = node["next"]
        elif node["type"] in _PAUSING_NODE_TYPES:
            entry["approvers"] = node.get("approvers") or node.get("assignee")
            break  # simulation shows the path UP TO the first real human step, not past it
        else:
            break
    return path
