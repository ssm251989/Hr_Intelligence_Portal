"""Global search -- Ctrl/Cmd+K (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 3; L-N3:
"candidates, employees, jobs, requests/approvals and settings (Postgres full-text + trigram,
permission-scoped)").

Every entity group is gated by its own view permission and, for employees, the caller's
org data scope; matching uses trigram similarity (pg_trgm GIN indexes from this part's
migration) with ILIKE as the candidate filter, so it also finds partial names and typos.
"""

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.core_hr import Employee
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.iam.org_scope import employee_ids_in_scope
from app.platform.tenancy.context import TenantContext

PER_GROUP = 5
MIN_QUERY = 2


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(db: Session, tenant: TenantContext, user: User, q: str) -> dict:
    q = (q or "").strip()
    if len(q) < MIN_QUERY:
        return {"query": q, "groups": []}
    pattern = _like(q)
    groups = []

    if has_permission(db, tenant, user, "recruitment.candidate.view"):
        sim = func.greatest(func.similarity(func.coalesce(Candidate.full_name, ""), q), func.similarity(func.coalesce(Candidate.email, ""), q))
        rows = (
            db.query(Candidate, sim.label("score")).filter(Candidate.tenant_id == tenant.tenant_id)
            .filter(or_(Candidate.full_name.ilike(pattern), Candidate.email.ilike(pattern), func.similarity(func.coalesce(Candidate.full_name, ""), q) > 0.3))
            .order_by(sim.desc()).limit(PER_GROUP).all()
        )
        groups.append({"type": "candidate", "label_key": "search.candidates", "items": [
            {"id": str(c.id), "title": c.full_name or c.email, "subtitle": c.location, "path": f"/candidates/list?candidate={c.id}"} for c, _ in rows]})

    if has_permission(db, tenant, user, "core_hr.employee.view"):
        full = Employee.first_name + " " + func.coalesce(Employee.last_name, "")  # same expression as ix_employees_name_trgm
        sim = func.greatest(func.similarity(full, q), func.similarity(Employee.employee_code, q))
        query = (
            db.query(Employee, sim.label("score")).filter(Employee.tenant_id == tenant.tenant_id)
            .filter(or_(full.ilike(pattern), Employee.employee_code.ilike(pattern), func.similarity(full, q) > 0.3))
        )
        scope = employee_ids_in_scope(db, tenant, user, "core_hr.employee.view")
        if scope is not None:
            query = query.filter(Employee.id.in_(list(scope))) if scope else query.filter(False)
        rows = query.order_by(sim.desc()).limit(PER_GROUP).all()
        groups.append({"type": "employee", "label_key": "search.employees", "items": [
            {"id": str(e.id), "title": " ".join(p for p in (e.first_name, e.last_name) if p), "subtitle": e.employee_code, "path": f"/settings#core-hr?employee={e.id}"}
            for e, _ in rows]})

    if has_permission(db, tenant, user, "recruitment.job.view"):
        sim = func.similarity(JobRole.title, q)
        rows = (
            db.query(JobRole, sim.label("score")).filter(JobRole.tenant_id == tenant.tenant_id)
            .filter(or_(JobRole.title.ilike(pattern), sim > 0.3)).order_by(sim.desc()).limit(PER_GROUP).all()
        )
        groups.append({"type": "job", "label_key": "search.jobs", "items": [
            {"id": str(j.id), "title": j.title, "subtitle": " · ".join(p for p in (j.department, j.location, j.status) if p), "path": f"/jobs?job={j.id}"} for j, _ in rows]})

    groups.append({"type": "request", "label_key": "search.requests", "items": _requests(db, tenant, user, q, pattern)})

    if has_permission(db, tenant, user, "platform.settings.view"):
        from app.platform.settings.help_catalog import HELP
        from app.platform.settings.registry import all_definitions

        lowered = q.lower()
        hits = [d for d in all_definitions() if lowered in d.key.lower() or lowered in (HELP.get(d.key, ("", ""))[0]).lower()][:PER_GROUP]
        groups.append({"type": "setting", "label_key": "search.settings", "items": [
            {"id": d.key, "title": d.key, "subtitle": HELP.get(d.key, ("", ""))[0], "path": f"/settings?setting={d.key}"} for d in hits]})

    if has_permission(db, tenant, user, "analytics.report.view"):
        from app.models.intelligence import SavedReport
        from app.platform.iam.roles import role_names_for

        roles = set(role_names_for(db, tenant, user))
        rows = db.query(SavedReport).filter(SavedReport.tenant_id == tenant.tenant_id, SavedReport.name.ilike(pattern)).limit(20).all()
        visible = [r for r in rows if r.owner_user_id == user.id or set(r.shared_role_names or []) & roles][:PER_GROUP]
        groups.append({"type": "report", "label_key": "search.reports", "items": [
            {"id": str(r.id), "title": r.name, "subtitle": r.dataset_code, "path": f"/reports?report={r.id}"} for r in visible]})

    return {"query": q, "groups": [g for g in groups if g["items"]]}


def _requests(db: Session, tenant: TenantContext, user: User, q: str, pattern: str) -> list[dict]:
    """Tickets the caller may see + approvals waiting on them / started by them."""
    items: list[dict] = []
    from app.models.service_desk import Ticket
    from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep
    from app.service_desk.tickets import visible_query

    if has_permission(db, tenant, user, "helpdesk.ticket.view"):
        query = visible_query(db, tenant, user=user, can_view_confidential=has_permission(db, tenant, user, "helpdesk.ticket.view_sensitive"))
    else:
        query = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.requester_user_id == user.id)
    for t in query.filter(or_(Ticket.number.ilike(pattern), Ticket.subject.ilike(pattern))).order_by(Ticket.created_at.desc()).limit(PER_GROUP).all():
        items.append({"id": str(t.id), "title": f"{t.number} · {t.subject}", "subtitle": t.status, "path": f"/settings#helpdesk?ticket={t.id}"})

    steps = (
        db.query(WorkflowStep, WorkflowInstance, WorkflowDefinition)
        .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
        .filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.assignee_user_id == user.id, WorkflowStep.status == "pending",
                or_(WorkflowDefinition.name.ilike(pattern), WorkflowInstance.entity_type.ilike(pattern)))
        .limit(PER_GROUP).all()
    )
    for step, instance, definition in steps:
        items.append({"id": str(step.id), "title": definition.name, "subtitle": f"awaiting you · {instance.entity_type}", "path": f"/approvals?step={step.id}"})
    return items[: PER_GROUP * 2]
