"""Part 15 step 15.6 -- People (Core HR) screen helpers. Read-only.

* GET /api/v1/ui/people/employees                 -- employees list / directory: each person with
  their CURRENT job record resolved to names (designation, department, office, manager) plus
  skills, filterable by q / status / department_id / location_id / skill.
* GET /api/v1/ui/people/filters                   -- departments, offices and skills that
  actually have people (with counts) for the filter chips.
* GET /api/v1/ui/people/employees/{id}/summary    -- profile header + Personal/Job tabs: the
  employee master (sensitive numbers masked), the current job with names resolved, job changes
  still waiting for approval (running core_hr.lifecycle.* workflow instances) and what the
  caller may do.
* GET /api/v1/ui/people/employees/{id}/history    -- employment history with names resolved +
  recent audited actions on this person (letters made, sensitive details viewed/changed).
* GET /api/v1/ui/people/letter-templates          -- published standard letters (latest version).
* GET /api/v1/ui/people/letters/{letter_id}       -- one generated letter's HTML (for preview).
* GET /api/v1/ui/people/org-chart                 -- the existing lazy org chart (one level per
  call, root_position_id) with who sits in each position.

Nothing here writes. Sensitive numbers are never decrypted here -- the existing audited
`GET /api/v1/core-hr/employees/{id}/encrypted-field/{field}` is the only reveal path. Field
security (Part 5A, entity "employee") is applied to every employee field returned, so a role
that has e.g. phone masked/hidden sees it masked/hidden here too. Tenant scoping: explicit
tenant_id filters + the TenantOwned ORM filter + Postgres RLS, same as core_hr/api_router.py.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/people", tags=["ui-people"])

_MASK = "••••"
_SENSITIVE_FIELDS = ("pan", "aadhaar", "passport", "visa", "driving_licence", "bank_account")
_LIST_LIMIT = 5000
_HISTORY_AUDIT_ACTIONS = (
    "employee_created", "letter_generated", "sensitive_field_revealed", "sensitive_field_set", "lifecycle_event_requested",
)


def _full_name(e) -> str:
    first = (e.preferred_name or e.first_name or "").strip()
    return " ".join(p for p in (first, (e.last_name or "").strip()) if p) or (e.employee_code or "")


def _skill_names(skills: Any) -> list[str]:
    out: list[str] = []
    for s in skills or []:
        name = s.get("skill") or s.get("name") if isinstance(s, dict) else s if isinstance(s, str) else None
        if name and str(name).strip() and str(name).strip() not in out:
            out.append(str(name).strip())
    return out


class _FieldGuard:
    """Field security for entity "employee", resolved ONCE per request (one query) and then
    applied to every row: hidden keys dropped, masked keys replaced."""

    def __init__(self, db: Session, tenant, user: User, keys: list[str]):
        from app.platform.iam.field_security import apply_field_security

        probe = apply_field_security(db, tenant, user, "employee", {k: k for k in keys})
        self.hidden = {k for k in keys if k not in probe}
        self.masked = {k for k, v in probe.items() if v != k}

    def apply(self, obj: dict) -> dict:
        out = {}
        for k, v in obj.items():
            if k in self.hidden:
                continue
            out[k] = _MASK if (k in self.masked and v not in (None, "", [], {})) else v
        return out


def _current_records(db: Session, tenant, employee_ids: Optional[list] = None) -> dict:
    """employee_id -> the employment_records row current today (latest effective_from <= today
    whose effective_to is open or not yet passed)."""
    from app.models.core_hr import EmploymentRecord

    today = datetime.now(timezone.utc).date()
    q = db.query(EmploymentRecord).filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.effective_from <= today)
    q = q.filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= today))
    if employee_ids is not None:
        if not employee_ids:
            return {}
        q = q.filter(EmploymentRecord.employee_id.in_(employee_ids))
    out: dict = {}
    for r in q.order_by(EmploymentRecord.effective_from.asc()).all():
        out[r.employee_id] = r  # ascending -> the latest wins
    return out


def _joined_on(db: Session, tenant, employee_ids: list) -> dict:
    from sqlalchemy import func

    from app.models.core_hr import EmploymentRecord

    if not employee_ids:
        return {}
    rows = (
        db.query(EmploymentRecord.employee_id, func.min(EmploymentRecord.effective_from))
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id.in_(employee_ids))
        .group_by(EmploymentRecord.employee_id)
        .all()
    )
    return {r[0]: r[1] for r in rows}


def _name_maps(db: Session, tenant) -> dict[str, dict]:
    from app.models.core_hr import CostCenter, Department, Location, Position

    tid = tenant.tenant_id
    return {
        "department": {d.id: d.name for d in db.query(Department).filter(Department.tenant_id == tid).all()},
        "location": {loc.id: loc.name for loc in db.query(Location).filter(Location.tenant_id == tid).all()},
        "position": {p.id: p.title for p in db.query(Position).filter(Position.tenant_id == tid).all()},
        "cost_center": {c.id: c.name for c in db.query(CostCenter).filter(CostCenter.tenant_id == tid).all()},
    }


def _iso(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, (date, datetime)) else None


def _sid(v) -> Optional[str]:
    return str(v) if v else None


def _job_dict(r, names: dict, people: dict) -> dict:
    if r is None:
        return {}
    return {
        "record_id": str(r.id), "effective_from": _iso(r.effective_from), "effective_to": _iso(r.effective_to), "event_type": r.event_type,
        "event_reason": r.event_reason,
        "designation": r.designation or (names["position"].get(r.position_id) if r.position_id else None),
        "department_id": _sid(r.department_id), "department": names["department"].get(r.department_id),
        "location_id": _sid(r.location_id), "location": names["location"].get(r.location_id),
        "position_id": _sid(r.position_id), "position": names["position"].get(r.position_id),
        "manager_id": _sid(r.manager_employee_id), "manager_name": people.get(r.manager_employee_id),
        "cost_center": names["cost_center"].get(r.cost_center_id),
        "grade": r.grade, "employment_type": r.employment_type, "work_mode": r.work_mode,
        "probation_end": _iso(r.probation_end), "confirmation_date": _iso(r.confirmation_date), "notice_period_days": r.notice_period_days,
    }


def _people_names(db: Session, tenant) -> dict:
    from app.models.core_hr import Employee

    return {e.id: _full_name(e) for e in db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).all()}


def _work_emails(db: Session, user_ids: list) -> dict:
    ids = [u for u in user_ids if u]
    if not ids:
        return {}
    return {u.id: u.email for u in db.query(User).filter(User.id.in_(ids)).all()}


def _get_employee(db: Session, tenant, employee_id: UUID):
    from app.models.core_hr import Employee

    e = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.id == employee_id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="We couldn't find this person.")
    return e


_LIST_KEYS = ["personal_email", "personal_phone", "skills", "work_email", "designation", "department", "location", "manager_name", "grade", "work_mode", "joined_on"]


# ---- employees list / directory ----


# Part 17.9: the People directory is for everyone in the company; it shows only these
# fields (no personal contact details, grade, dates or codes). The HR view keeps the full row.
_DIRECTORY_KEYS = ("id", "name", "first_name", "last_name", "status", "photo_url", "designation", "department_id", "department",
                   "location_id", "location", "manager_id", "manager_name", "work_mode", "work_email", "skills")
_DIRECTORY_STATUSES = ("active", "on_notice")


def _directory_mode(db: Session, tenant, user: User, view: str) -> bool:
    """True = directory fields only. The HR view needs core_hr.employee.view; the directory
    only needs a staff login (agency logins never reach here -- auth/dependencies.py)."""
    if view not in ("hr", "directory"):
        raise HTTPException(status_code=400, detail="view must be hr or directory")
    full = has_permission(db, tenant, user, "core_hr.employee.view")
    if view == "hr" and not full:
        raise HTTPException(status_code=403, detail="Missing permission: core_hr.employee.view")
    return view == "directory"


@router.get("/employees")
def list_people(
    q: Optional[str] = None, status: Optional[str] = None, department_id: Optional[UUID] = None, location_id: Optional[UUID] = None,
    skill: Optional[str] = None, view: str = "hr", db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    from app.models.core_hr import Employee

    tenant = require_current_tenant()
    directory = _directory_mode(db, tenant, current_user, view)
    query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id)
    if directory:
        query = query.filter(Employee.status.in_(_DIRECTORY_STATUSES))
    if status:
        query = query.filter(Employee.status.in_([s for s in status.split(",") if s]))
    employees = query.order_by(Employee.first_name, Employee.last_name).limit(_LIST_LIMIT).all()
    ids = [e.id for e in employees]
    current = _current_records(db, tenant, ids)
    joined = _joined_on(db, tenant, ids)
    names = _name_maps(db, tenant)
    people = _people_names(db, tenant)
    emails = _work_emails(db, [e.user_id for e in employees])
    guard = _FieldGuard(db, tenant, current_user, _LIST_KEYS)

    needle = (q or "").strip().lower()
    skill_needle = (skill or "").strip().lower()
    items = []
    for e in employees:
        r = current.get(e.id)
        if department_id and (r is None or r.department_id != department_id):
            continue
        if location_id and (r is None or r.location_id != location_id):
            continue
        skills = _skill_names(e.skills_json)
        if skill_needle and not any(s.lower() == skill_needle for s in skills):
            continue
        job = _job_dict(r, names, people)
        row = {
            "id": str(e.id), "employee_code": e.employee_code, "name": _full_name(e), "first_name": e.first_name, "last_name": e.last_name,
            "status": e.status, "worker_type": e.worker_type, "photo_url": None,
            "designation": job.get("designation"), "department_id": job.get("department_id"), "department": job.get("department"),
            "location_id": job.get("location_id"), "location": job.get("location"), "manager_id": job.get("manager_id"),
            "manager_name": job.get("manager_name"), "grade": job.get("grade"), "work_mode": job.get("work_mode"),
            "joined_on": _iso(joined.get(e.id)), "work_email": emails.get(e.user_id), "personal_email": e.personal_email,
            "personal_phone": e.personal_phone, "skills": skills,
        }
        if needle:
            hay = " ".join(str(v) for v in (row["name"], row["employee_code"], row["designation"], row["department"], row["location"], row["work_email"], " ".join(skills)) if v).lower()
            if needle not in hay:
                continue
        row = guard.apply(row)
        items.append({k: row[k] for k in _DIRECTORY_KEYS if k in row} if directory else row)
    return {"items": items, "total": len(items), "truncated": len(employees) >= _LIST_LIMIT}


@router.get("/filters")
def people_filters(view: str = "hr", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import Employee

    tenant = require_current_tenant()
    _directory_mode(db, tenant, current_user, view)
    employees = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).all()
    current = _current_records(db, tenant)
    names = _name_maps(db, tenant)
    dept: dict = {}
    loc: dict = {}
    skills: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for e in employees:
        statuses[e.status] = statuses.get(e.status, 0) + 1
        r = current.get(e.id)
        if r is not None and r.department_id in names["department"]:
            dept[r.department_id] = dept.get(r.department_id, 0) + 1
        if r is not None and r.location_id in names["location"]:
            loc[r.location_id] = loc.get(r.location_id, 0) + 1
        for s in _skill_names(e.skills_json):
            skills[s] = skills.get(s, 0) + 1
    guard = _FieldGuard(db, tenant, current_user, ["skills"])
    return {
        # Every department/office is listed (count 0 when nobody is there yet) so the job-change
        # form can offer them too; the filter chips hide the empty ones.
        "departments": sorted(({"id": str(k), "name": v, "count": dept.get(k, 0)} for k, v in names["department"].items()), key=lambda x: x["name"].lower()),
        "locations": sorted(({"id": str(k), "name": v, "count": loc.get(k, 0)} for k, v in names["location"].items()), key=lambda x: x["name"].lower()),
        "skills": [] if ("skills" in guard.hidden or "skills" in guard.masked) else sorted(({"name": k, "count": v} for k, v in skills.items()), key=lambda x: (-x["count"], x["name"].lower()))[:200],
        "statuses": statuses,
        "total": len(employees),
    }


# ---- profile ----


def _pending_changes(db: Session, tenant, employee_id: UUID) -> list[dict]:
    from app.models.workflow import WorkflowInstance

    rows = (
        db.query(WorkflowInstance)
        .filter(
            WorkflowInstance.tenant_id == tenant.tenant_id, WorkflowInstance.entity_type == "employment_record",
            WorkflowInstance.entity_id == employee_id, WorkflowInstance.status == "running",
        )
        .order_by(WorkflowInstance.started_at.desc())
        .all()
    )
    out = []
    for i in rows:
        ctx = i.context_json or {}
        out.append({
            "id": str(i.id), "event_type": ctx.get("event_type"), "effective_from": ctx.get("effective_from"),
            "changes": sorted((ctx.get("changes") or {}).keys()), "reason": ctx.get("reason"),
            "requested_by": i.started_by, "requested_at": _iso(i.started_at),
        })
    return out


@router.get("/employees/{employee_id}/summary")
def employee_summary(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    from app.core_hr import employees as employees_service

    tenant = require_current_tenant()
    e = _get_employee(db, tenant, employee_id)
    names = _name_maps(db, tenant)
    people = _people_names(db, tenant)
    current = _current_records(db, tenant, [e.id]).get(e.id)
    joined = _joined_on(db, tenant, [e.id]).get(e.id)
    job = _job_dict(current, names, people)
    base = employees_service.employee_to_dict(e)
    # Sensitive numbers: presence + a safe masked form only (never decrypted here).
    sensitive = {}
    for f in _SENSITIVE_FIELDS:
        present = bool(getattr(e, f"{f}_secret_ref", None))
        masked = employees_service.masked_aadhaar(e) if f == "aadhaar" else ("XXXXXXXX" if present else None)
        sensitive[f] = {"present": present, "masked": masked}
    for f in _SENSITIVE_FIELDS:
        base.pop(f, None)
    work_email = _work_emails(db, [e.user_id]).get(e.user_id)
    person = {**base, "name": _full_name(e), "photo_url": None, "work_email": work_email, "joined_on": _iso(joined)}
    job_keys = list(job.keys())
    guard = _FieldGuard(db, tenant, current_user, list(person.keys()) + job_keys + list(_SENSITIVE_FIELDS))
    # custom fields go through the same field-security rules (a custom field's code IS its field name)
    custom = person.get("custom_fields") or {}
    if isinstance(custom, dict) and custom:
        cguard = _FieldGuard(db, tenant, current_user, list(custom.keys()))
        person["custom_fields"] = cguard.apply(custom)
    reports = sum(1 for r in _current_records(db, tenant).values() if r.manager_employee_id == e.id)
    return {
        "person": guard.apply(person),
        "job": guard.apply(job) if job else None,
        "sensitive": {k: v for k, v in sensitive.items() if k not in guard.hidden},
        "pending_changes": _pending_changes(db, tenant, e.id),
        "direct_reports": reports,
        "can": {
            "edit_job": has_permission(db, tenant, current_user, "core_hr.employment.create"),
            "edit_sensitive": has_permission(db, tenant, current_user, "core_hr.employee.edit"),
            "reveal": has_permission(db, tenant, current_user, "core_hr.employee.view_sensitive"),
            "view_history": has_permission(db, tenant, current_user, "core_hr.employment.view"),
            "letters_view": has_permission(db, tenant, current_user, "core_hr.letter.view"),
            "letters_create": has_permission(db, tenant, current_user, "core_hr.letter.create"),
            "add_document": has_permission(db, tenant, current_user, "core_hr.employee.edit"),
        },
    }


@router.get("/employees/{employee_id}/history")
def employee_history(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employment.view"))):
    from app.core_hr import lifecycle
    from app.models.audit_log import AuditLog

    tenant = require_current_tenant()
    e = _get_employee(db, tenant, employee_id)
    names = _name_maps(db, tenant)
    people = _people_names(db, tenant)
    records = [_job_dict(r, names, people) | {"created_by": r.created_by} for r in lifecycle.employment_history(db, tenant, e.id)]
    events = (
        db.query(AuditLog)
        .filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_type == "employee", AuditLog.entity_id == e.id, AuditLog.action.in_(_HISTORY_AUDIT_ACTIONS))
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    activity = []
    for a in events:
        d = a.details or {}
        activity.append({
            "id": str(a.id), "action": a.action, "actor": a.actor, "at": _iso(a.created_at),
            "field": d.get("field"), "letter": d.get("template_key"), "event_type": d.get("event_type"), "applied": d.get("applied"),
        })
    return {"records": records, "activity": activity, "pending_changes": _pending_changes(db, tenant, e.id)}


# ---- letters ----


@router.get("/letter-templates")
def letter_templates(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.view"))):
    from app.models.core_hr import LetterTemplate

    tenant = require_current_tenant()
    rows = (
        db.query(LetterTemplate)
        .filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.status == "published")
        .order_by(LetterTemplate.key, LetterTemplate.version.desc())
        .all()
    )
    seen: dict[str, dict] = {}
    for t in rows:
        if t.key not in seen:
            seen[t.key] = {"key": t.key, "name": t.name, "version": t.version}
    return list(seen.values())


@router.get("/letters/{letter_id}")
def letter_detail(letter_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.view"))):
    from app.models.core_hr import LetterRecord

    tenant = require_current_tenant()
    r = db.query(LetterRecord).filter(LetterRecord.tenant_id == tenant.tenant_id, LetterRecord.id == letter_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="We couldn't find this letter.")
    return {
        "id": str(r.id), "employee_id": str(r.employee_id), "template_key": r.template_key, "rendered_html": r.rendered_html,
        "generated_at": _iso(r.generated_at), "generated_by": r.generated_by, "verification_token": r.verification_token,
    }


# ---- org chart ----


@router.get("/org-chart")
def org_chart(root_position_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.org.view"))):
    from app.core_hr import org as org_service

    tenant = require_current_tenant()
    nodes = org_service.org_chart_by_position(db, tenant, root_position_id)
    if not nodes:
        return {"nodes": []}
    pos_ids = [UUID(n["id"]) for n in nodes]
    from app.models.core_hr import Employee, EmploymentRecord, Position

    today = datetime.now(timezone.utc).date()
    holders: dict = {}
    recs = (
        db.query(EmploymentRecord)
        .filter(EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.position_id.in_(pos_ids), EmploymentRecord.effective_from <= today)
        .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= today))
        .all()
    )
    emp_ids = list({r.employee_id for r in recs})
    emps = {e.id: e for e in db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.id.in_(emp_ids)).all()} if emp_ids else {}
    for r in recs:
        e = emps.get(r.employee_id)
        if e is None or e.status in ("terminated", "inactive"):
            continue
        holders.setdefault(r.position_id, []).append({"employee_id": str(e.id), "name": _full_name(e), "photo_url": None, "status": e.status})
    names = _name_maps(db, tenant)
    positions = {p.id: p for p in db.query(Position).filter(Position.tenant_id == tenant.tenant_id, Position.id.in_(pos_ids)).all()}
    from sqlalchemy import func

    child_counts = dict(
        db.query(Position.reports_to_position_id, func.count(Position.id))
        .filter(Position.tenant_id == tenant.tenant_id, Position.reports_to_position_id.in_(pos_ids))
        .group_by(Position.reports_to_position_id)
        .all()
    )
    out = []
    for n in nodes:
        pid = UUID(n["id"])
        p = positions.get(pid)
        out.append({
            **n, "department": names["department"].get(p.department_id) if p else None, "location": names["location"].get(p.location_id) if p else None,
            "holders": holders.get(pid, []), "children_count": int(child_counts.get(pid, 0)),
        })
    return {"nodes": out}
