"""Job requisitions (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 2) -- the headcount
approval step that precedes posting a job. Approval reuses Part 5's workflow engine via
the exact same "un-gated if no published workflow_definition for this key" pattern Part
7's `core_hr.lifecycle.request_event` already established: `request_approval()` starts a
real workflow instance when a published `workflow_definitions` row exists for key
`recruitment.job_requisition_approval` -- Part 5's own `hrctl.seed_workflows` already
seeds and publishes this exact key for tenant #1 (see its own `_definitions()` list), so
in this build's real environment every requisition genuinely gates behind a Hiring
Manager approval step; a tenant with no such definition published gets the un-gated
immediate-approve fallback instead."""

REQUISITION_APPROVAL_WORKFLOW_KEY = "recruitment.job_requisition_approval"

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.requisition import JobRequisition
from app.platform.tenancy.context import TenantContext


def create_requisition(
    db: Session, tenant: TenantContext, *, title: str, reason: str = "new", headcount: int = 1,
    position_id: Optional[UUID] = None, department_id: Optional[UUID] = None, budget: Optional[float] = None,
    justification: Optional[str] = None, requested_by: Optional[str] = None,
) -> JobRequisition:
    requisition = JobRequisition(
        tenant_id=tenant.tenant_id, title=title, reason=reason, headcount=headcount, position_id=position_id,
        department_id=department_id, budget=budget, justification=justification, status="draft", requested_by=requested_by,
    )
    db.add(requisition)
    db.commit()
    db.refresh(requisition)
    return requisition


def request_approval(db: Session, tenant: TenantContext, requisition_id: UUID, *, requested_by_user_id=None, actor_email: Optional[str] = None) -> dict:
    from app.platform.workflow import definitions as workflow_definitions
    from app.platform.workflow import engine as workflow_engine

    requisition = db.get(JobRequisition, requisition_id)
    if requisition is None or requisition.tenant_id != tenant.tenant_id:
        raise ValueError("Requisition not found")

    try:
        definition = workflow_definitions.get_published_definition(db, tenant.tenant_id, REQUISITION_APPROVAL_WORKFLOW_KEY)
    except workflow_definitions.DefinitionNotFoundError:
        requisition.status = "approved"
        db.commit()
        db.refresh(requisition)
        return {"applied": True, "status": requisition.status}

    requisition.status = "pending_approval"
    instance = workflow_engine.start_instance(
        db, tenant, definition, entity_type="job_requisition", entity_id=requisition.id,
        context={"requisition_id": str(requisition.id), "title": requisition.title, "headcount": requisition.headcount, "budget": float(requisition.budget) if requisition.budget is not None else None},
        started_by=actor_email, started_by_user_id=requested_by_user_id,
    )
    requisition.workflow_instance_id = instance.id
    db.commit()
    db.refresh(requisition)
    return {"applied": False, "workflow_instance_id": instance.id}


def apply_from_approved_workflow(db: Session, tenant: TenantContext, instance_id: UUID) -> Optional[JobRequisition]:
    """Mirrors core_hr.lifecycle.apply_from_approved_workflow's own pattern -- called once
    a `recruitment.requisition.approve` workflow instance completes."""
    from app.models.workflow import WorkflowInstance

    instance = db.get(WorkflowInstance, instance_id)
    if instance is None or instance.entity_type != "job_requisition" or instance.status != "completed":
        return None
    requisition = db.get(JobRequisition, UUID(instance.context_json["requisition_id"]))
    if requisition is None:
        return None
    requisition.status = "approved" if instance.context_json.get("outcome") == "approved" else "rejected"
    db.commit()
    db.refresh(requisition)
    return requisition


def list_requisitions(db: Session, tenant: TenantContext, *, status: Optional[str] = None) -> list[JobRequisition]:
    query = db.query(JobRequisition).filter(JobRequisition.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(JobRequisition.status == status)
    return query.order_by(JobRequisition.created_at.desc()).all()
