"""Workflow definition CRUD + publish (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 1) --
same versioned draft->published->retired lifecycle as Part 4's message_templates."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowDefinition


class DefinitionNotFoundError(Exception):
    pass


class DefinitionValidationError(Exception):
    pass


def get_published_definition(db: Session, tenant_id: UUID, key: str) -> WorkflowDefinition:
    definition = (
        db.query(WorkflowDefinition)
        .filter(WorkflowDefinition.tenant_id == tenant_id, WorkflowDefinition.key == key, WorkflowDefinition.status == "published")
        .order_by(WorkflowDefinition.version.desc())
        .first()
    )
    if definition is None:
        raise DefinitionNotFoundError(f"No published workflow_definition for key: {key}")
    return definition


def create_draft(
    db: Session, tenant_id: UUID, *, key: str, name: str, module: Optional[str] = None,
    trigger: dict, graph: dict,
) -> WorkflowDefinition:
    latest = (
        db.query(WorkflowDefinition)
        .filter(WorkflowDefinition.tenant_id == tenant_id, WorkflowDefinition.key == key)
        .order_by(WorkflowDefinition.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1
    definition = WorkflowDefinition(
        tenant_id=tenant_id, key=key, name=name, module=module, version=next_version,
        status="draft", trigger_json=trigger, graph_json=graph,
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def _validate_graph(graph: dict) -> None:
    start_node = graph.get("start_node")
    nodes = graph.get("nodes", {})
    if not start_node or start_node not in nodes:
        raise DefinitionValidationError("graph_json.start_node must reference a real node")
    referenced = {start_node}
    for node_id, node in nodes.items():
        for key in ("next", "on_true", "on_false", "default", "on_approve", "on_reject", "on_send_back"):
            if node.get(key):
                referenced.add(node[key])
        for case in node.get("cases", []):
            if case.get("next"):
                referenced.add(case["next"])
        for branch in node.get("branches", []):
            referenced.add(branch)
    unreachable = referenced - set(nodes)
    if unreachable:
        raise DefinitionValidationError(f"graph_json references undefined node(s): {sorted(unreachable)}")
    if not any(n.get("type") == "end" for n in nodes.values()):
        raise DefinitionValidationError("graph_json has no 'end' node -- every path must be able to terminate")


def publish(db: Session, definition: WorkflowDefinition, *, actor: str) -> WorkflowDefinition:
    _validate_graph(definition.graph_json)
    definition.status = "published"
    definition.created_by = definition.created_by or actor
    definition.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(definition)
    return definition


def retire(db: Session, definition: WorkflowDefinition) -> WorkflowDefinition:
    definition.status = "retired"
    db.commit()
    db.refresh(definition)
    return definition
