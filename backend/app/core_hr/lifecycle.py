"""LifecycleService (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 3, named directly in this
part's own CHECKS) -- every employment change is a NEW, effective-dated `employment_
records` row, never an in-place edit of a previous one ("no silent edits of job info").

**Workflow gating** (section 3's own "each driven by a workflow from Part 5"): `request_
event()` starts a real workflow instance (via `platform.workflow.engine`) when the event's
own `workflow_definitions` row exists for this tenant, storing the proposed employment_
records field values in the instance's own `context_json` -- nothing is written to
`employment_records` until `apply_event()` actually runs, which the workflow's own
approval endpoint calls once resolved (see api_router.py's own workflow-completion
handling). An event with no matching published workflow_definition applies immediately,
un-gated -- not every one of section 3's 18 event types needs approval for every tenant,
and this build hasn't seeded a workflow_definition for most of them (see docs/
build_log.md's own Part 7 note for exactly which ones are seeded).

**Future-dated changes** (section 3's own "applied by scheduler on effective date"): a
row with `effective_from` in the future is created immediately (so it's visible/auditable
right away), but `get_current_employment()`'s own as-of logic naturally treats it as not-
yet-current until that date arrives -- no separate scheduler flips anything, since the
data itself already encodes when it takes effect. What's NOT built is a job that emits
`employment.changed`/updates `employees.status` exactly ON that date -- the same
documented Celery-beat gap as every other "needs a live scheduler" capability in this
build (Parts 2/4/5's own).
"""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import EmploymentRecord, LIFECYCLE_EVENT_TYPES
from app.platform.tenancy.context import TenantContext

_EMPLOYMENT_FIELDS = (
    "legal_entity_id", "business_unit_id", "department_id", "location_id", "position_id", "designation",
    "grade", "manager_employee_id", "functional_manager_employee_id", "hrbp_employee_id", "cost_center_id",
    "employment_type", "probation_end", "confirmation_date", "notice_period_days", "work_mode",
)


class InvalidLifecycleEventError(Exception):
    pass


def get_current_employment(db: Session, tenant: TenantContext, employee_id: UUID, *, as_of: Optional[date] = None) -> Optional[EmploymentRecord]:
    """The as-of-date query section 3's own TESTS name explicitly -- the row whose
    [effective_from, effective_to) window contains `as_of` (default today)."""
    as_of = as_of or datetime.now(timezone.utc).date()
    return (
        db.query(EmploymentRecord)
        .filter(
            EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id == employee_id,
            EmploymentRecord.effective_from <= as_of,
        )
        .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= as_of))
        .order_by(EmploymentRecord.effective_from.desc())
        .first()
    )


def employment_history(db: Session, tenant: TenantContext, employee_id: UUID) -> list[EmploymentRecord]:
    return (
        db.query(EmploymentRecord)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id == employee_id)
        .order_by(EmploymentRecord.effective_from.desc())
        .all()
    )


def apply_event(
    db: Session, tenant: TenantContext, *, employee_id: UUID, event_type: str, effective_from: date,
    changes: dict, reason: Optional[str] = None, created_by: Optional[str] = None,
    workflow_instance_id: Optional[UUID] = None,
) -> EmploymentRecord:
    """The actual mutation: closes out whatever employment_records row was current
    immediately before `effective_from` (sets its `effective_to`) and inserts the new
    one. `changes` is a dict of `_EMPLOYMENT_FIELDS` keys -- any field NOT in `changes`
    carries forward from the immediately-preceding record (a transfer changing only
    `department_id` doesn't require re-specifying the employee's manager/grade/etc)."""
    if event_type not in LIFECYCLE_EVENT_TYPES:
        raise InvalidLifecycleEventError(f"Unknown lifecycle event_type: {event_type!r}")
    unknown_fields = set(changes) - set(_EMPLOYMENT_FIELDS)
    if unknown_fields:
        raise InvalidLifecycleEventError(f"Unknown employment field(s): {sorted(unknown_fields)}")

    previous = get_current_employment(db, tenant, employee_id, as_of=effective_from)
    carried_forward = {field: getattr(previous, field) for field in _EMPLOYMENT_FIELDS} if previous else {}
    if previous is not None and (previous.effective_to is None or previous.effective_to >= effective_from):
        from datetime import timedelta

        previous.effective_to = effective_from - timedelta(days=1)

    record = EmploymentRecord(
        tenant_id=tenant.tenant_id, employee_id=employee_id, effective_from=effective_from,
        event_type=event_type, event_reason=reason, created_by=created_by, workflow_instance_id=workflow_instance_id,
        **{**carried_forward, **changes},
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    from app.core_hr.events import emit_employment_changed

    emit_employment_changed(db, tenant, employee_id=employee_id, event_type=event_type)
    return record


def request_event(
    db: Session, tenant: TenantContext, *, employee_id: UUID, event_type: str, effective_from: date,
    changes: dict, reason: Optional[str] = None, created_by: Optional[str] = None, requested_by_user_id: Optional[UUID] = None,
) -> dict:
    """Returns {"applied": True, "record": EmploymentRecord} if there's no matching
    published workflow for this event_type (applies immediately), or {"applied": False,
    "workflow_instance_id": UUID} if a real one exists (gated -- apply_event() runs later,
    once that instance's approval resolves)."""
    from app.platform.workflow import definitions as workflow_definitions
    from app.platform.workflow import engine as workflow_engine

    workflow_key = f"core_hr.lifecycle.{event_type}"
    try:
        definition = workflow_definitions.get_published_definition(db, tenant.tenant_id, workflow_key)
    except workflow_definitions.DefinitionNotFoundError:
        record = apply_event(db, tenant, employee_id=employee_id, event_type=event_type, effective_from=effective_from, changes=changes, reason=reason, created_by=created_by)
        return {"applied": True, "record": record}

    instance = workflow_engine.start_instance(
        db, tenant, definition, entity_type="employment_record", entity_id=employee_id,
        context={
            "employee_id": str(employee_id), "event_type": event_type, "effective_from": effective_from.isoformat(),
            "changes": changes, "reason": reason, "created_by": created_by,
        },
        started_by=created_by, started_by_user_id=requested_by_user_id,
    )
    return {"applied": False, "workflow_instance_id": instance.id}


def apply_from_approved_workflow(db: Session, tenant: TenantContext, instance_id: UUID) -> Optional[EmploymentRecord]:
    """Called once a `core_hr.lifecycle.*` workflow instance completes with outcome
    "approved" -- replays its own stored context_json into apply_event(). Returns None
    (a no-op) for any other outcome (rejected/cancelled/still-running) or entity_type."""
    from datetime import date as date_cls

    from app.models.workflow import WorkflowInstance

    instance = db.get(WorkflowInstance, instance_id)
    if instance is None or instance.entity_type != "employment_record" or instance.status != "completed":
        return None
    ctx = instance.context_json
    if ctx.get("outcome") != "approved":
        return None
    return apply_event(
        db, tenant, employee_id=UUID(ctx["employee_id"]), event_type=ctx["event_type"],
        effective_from=date_cls.fromisoformat(ctx["effective_from"]), changes=ctx["changes"],
        reason=ctx.get("reason"), created_by=ctx.get("created_by"), workflow_instance_id=instance.id,
    )
