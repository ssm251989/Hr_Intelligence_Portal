"""Onboarding plans (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 3): a template's tasks
become real `onboarding_tasks` rows with due dates relative to the case's DOJ (-7d, day 1,
+30d), dependency blocking, and owner-role routing. Provisioning actions ("create email
account", access card, asset allocation) are checklist tasks at launch -- the spec's own
wording -- so they are ordinary tasks with `kind="provisioning"`, not connector calls.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.onboarding import (
    ONBOARDING_OWNER_ROLES,
    OnboardingPlan,
    OnboardingPlanTemplate,
    OnboardingTask,
    PreboardingCase,
)
from app.platform.tenancy.context import TenantContext


class InvalidPlanTemplateError(ValueError):
    pass


class TaskBlockedError(Exception):
    pass


def validate_tasks(tasks: list[dict]) -> None:
    keys = [t.get("key") for t in tasks]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        raise InvalidPlanTemplateError("every task needs a unique, non-empty key")
    for task in tasks:
        if not task.get("title"):
            raise InvalidPlanTemplateError(f"task {task['key']!r} needs a title")
        if task.get("owner_role") not in ONBOARDING_OWNER_ROLES:
            raise InvalidPlanTemplateError(f"task {task['key']!r}: owner_role must be one of {ONBOARDING_OWNER_ROLES}")
        if not isinstance(task.get("due_offset_days", 0), int):
            raise InvalidPlanTemplateError(f"task {task['key']!r}: due_offset_days must be an integer")
        for dep in task.get("depends_on", []):
            if dep not in keys:
                raise InvalidPlanTemplateError(f"task {task['key']!r} depends on unknown task {dep!r}")
    # cycle check -- a plan whose dependencies loop could never complete
    graph = {t["key"]: list(t.get("depends_on", [])) for t in tasks}
    visiting, done = set(), set()

    def _visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise InvalidPlanTemplateError(f"dependency cycle through {node!r}")
        visiting.add(node)
        for dep in graph[node]:
            _visit(dep)
        visiting.discard(node)
        done.add(node)

    for key in graph:
        _visit(key)


def upsert_template(db: Session, tenant: TenantContext, *, code: str, name: str, tasks: list[dict]) -> OnboardingPlanTemplate:
    validate_tasks(tasks)
    template = db.query(OnboardingPlanTemplate).filter(OnboardingPlanTemplate.tenant_id == tenant.tenant_id, OnboardingPlanTemplate.code == code).first()
    if template is None:
        template = OnboardingPlanTemplate(tenant_id=tenant.tenant_id, code=code, name=name, tasks_json=tasks)
        db.add(template)
    else:
        template.name = name
        template.tasks_json = tasks
    db.commit()
    db.refresh(template)
    return template


def get_template(db: Session, tenant: TenantContext, code: str) -> Optional[OnboardingPlanTemplate]:
    return (
        db.query(OnboardingPlanTemplate)
        .filter(OnboardingPlanTemplate.tenant_id == tenant.tenant_id, OnboardingPlanTemplate.code == code, OnboardingPlanTemplate.is_active.is_(True))
        .first()
    )


def due_date_for(joining_date: date, offset_days: int) -> date:
    return joining_date + timedelta(days=offset_days)


def generate_plan(db: Session, tenant: TenantContext, case: PreboardingCase, template: OnboardingPlanTemplate) -> OnboardingPlan:
    """Idempotent per case (unique on case_id): calling again returns the existing plan
    without duplicating tasks."""
    existing = db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == tenant.tenant_id, OnboardingPlan.case_id == case.id).first()
    if existing is not None:
        return existing
    plan = OnboardingPlan(tenant_id=tenant.tenant_id, case_id=case.id, template_id=template.id, template_code=template.code)
    db.add(plan)
    db.flush()
    for task in template.tasks_json or []:
        offset = int(task.get("due_offset_days", 0))
        depends_on = list(task.get("depends_on", []))
        db.add(OnboardingTask(
            tenant_id=tenant.tenant_id, plan_id=plan.id, key=task["key"], title=task["title"],
            kind=task.get("kind", "task"), owner_role=task["owner_role"], due_offset_days=offset,
            due_date=due_date_for(case.joining_date, offset), depends_on_json=depends_on,
            form_code=task.get("form_code"), status="blocked" if depends_on else "pending",
        ))
    db.commit()
    db.refresh(plan)
    return plan


def plan_tasks(db: Session, tenant: TenantContext, plan_id: UUID) -> list[OnboardingTask]:
    return (
        db.query(OnboardingTask)
        .filter(OnboardingTask.tenant_id == tenant.tenant_id, OnboardingTask.plan_id == plan_id)
        .order_by(OnboardingTask.due_date.asc(), OnboardingTask.key.asc())
        .all()
    )


def reschedule(db: Session, tenant: TenantContext, plan: OnboardingPlan, new_joining_date: date) -> None:
    """Joining-date change: every not-yet-done task keeps its offset, due date moves."""
    for task in plan_tasks(db, tenant, plan.id):
        if task.status not in ("done", "skipped"):
            task.due_date = due_date_for(new_joining_date, task.due_offset_days)
    db.commit()


def _unblock_dependents(db: Session, tenant: TenantContext, plan_id: UUID) -> None:
    tasks = plan_tasks(db, tenant, plan_id)
    finished = {t.key for t in tasks if t.status in ("done", "skipped")}
    for task in tasks:
        if task.status == "blocked" and all(dep in finished for dep in task.depends_on_json or []):
            task.status = "pending"


def complete_task(
    db: Session, tenant: TenantContext, task: OnboardingTask, *, actor: str, response: Optional[dict] = None, skip: bool = False,
) -> OnboardingTask:
    if task.status == "blocked":
        raise TaskBlockedError(f"task {task.key!r} is waiting on {task.depends_on_json}")
    if task.status in ("done", "skipped"):
        return task
    task.status = "skipped" if skip else "done"
    task.completed_by = actor
    task.completed_at = datetime.now(timezone.utc)
    if response is not None:
        task.response_json = response
    db.flush()
    _unblock_dependents(db, tenant, task.plan_id)
    db.commit()
    db.refresh(task)
    return task


def overdue_tasks(db: Session, tenant: TenantContext, *, today: Optional[date] = None) -> list[OnboardingTask]:
    today = today or datetime.now(timezone.utc).date()
    return (
        db.query(OnboardingTask)
        .filter(OnboardingTask.tenant_id == tenant.tenant_id, OnboardingTask.status.in_(("pending", "blocked")), OnboardingTask.due_date < today)
        .order_by(OnboardingTask.due_date.asc())
        .all()
    )


def task_to_dict(task: OnboardingTask) -> dict:
    return {
        "id": str(task.id), "plan_id": str(task.plan_id), "key": task.key, "title": task.title, "kind": task.kind,
        "owner_role": task.owner_role, "owner_user_id": str(task.owner_user_id) if task.owner_user_id else None,
        "due_offset_days": task.due_offset_days, "due_date": task.due_date.isoformat(), "depends_on": task.depends_on_json or [],
        "form_code": task.form_code, "status": task.status, "completed_by": task.completed_by,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None, "response": task.response_json,
    }
