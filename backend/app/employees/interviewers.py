"""Part 20.4: an employee as interviewer.

- Make interviewer (Employees list / profile): adds the Interviewer role, creates their availability (company
  email, Mon-Fri 10:00-18:00, 3 a day by default - they change it under My availability), skills, and adds them
  to the chosen pools. Remove interviewer takes them out of the pools and drops the role (availability kept).
- Auto rule (Settings `employees.interviewer.auto_rules`, e.g. [{"field": "designation", "contains": "lead"}]):
  new employees who match get the Interviewer role and availability when they are created.
- Existing interviewers (availability rows from the old Excel, e.g. jr@ctdtechs.com) are linked to an employee by
  email; with no match HR gets a to-do to link or create the employee.
"""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Employee
from app.models.interviewer_availability import InterviewerAvailability
from app.models.interviewer_pool import InterviewerPool
from app.models.user import User

DEFAULT_WEEK = {d: [{"start": "10:00", "end": "18:00"}] for d in ("mon", "tue", "wed", "thu", "fri")} | {"sat": False, "sun": False}


class InterviewerError(ValueError):
    pass


def _name(e: Employee) -> str:
    return " ".join(p for p in (e.first_name, e.last_name) if p)


def _address(db: Session, e: Employee) -> Optional[str]:
    user = db.get(User, e.user_id) if e.user_id else None
    return (e.company_email or (user.email if user else None) or "").strip().lower() or None


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def availability_for(db: Session, tenant, e: Employee) -> Optional[InterviewerAvailability]:
    addr = _address(db, e)
    q = db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id)
    return (q.filter(InterviewerAvailability.employee_id == e.id).first()
            or (q.filter(func.lower(InterviewerAvailability.interviewer_email) == addr).first() if addr else None))


def ensure_availability(db: Session, tenant, e: Employee, *, skills: Optional[list] = None, max_per_day: Optional[int] = None, actor: str) -> InterviewerAvailability:
    addr = _address(db, e)
    if not addr:
        raise InterviewerError("This employee has no company email or app login yet - interview invites need one.")
    row = availability_for(db, tenant, e)
    if row is None:
        row = InterviewerAvailability(tenant_id=tenant.tenant_id, interviewer_email=addr, interviewer_name=_name(e), employee_id=e.id,
                                      weekly_pattern_json=DEFAULT_WEEK, exceptions_json=[], max_interviews_per_day=max_per_day or 3,
                                      skills_json=[s for s in (skills or []) if s], source="employee")
        db.add(row)
    else:
        row.employee_id, row.interviewer_name = e.id, row.interviewer_name or _name(e)
        if skills is not None:
            row.skills_json = list(dict.fromkeys([*(row.skills_json or []), *[s for s in skills if s]]))
        if max_per_day:
            row.max_interviews_per_day = max_per_day
    db.commit()
    return row


def make_interviewer(db: Session, tenant, e: Employee, *, pool_ids: list, skills: list, max_per_day: Optional[int], actor: str) -> dict:
    from app.employees.roles import add_roles

    if e.status not in ("active", "on_notice"):
        raise InterviewerError("Only an active employee can interview.")
    user = db.get(User, e.user_id) if e.user_id else None
    if user is None:
        raise InterviewerError("Create their app account first (Resend app invite) - interviewers sign in to give feedback.")
    row = ensure_availability(db, tenant, e, skills=skills, max_per_day=max_per_day, actor=actor)
    add_roles(db, tenant, user, ["Interviewer"])
    added = []
    for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.id.in_(pool_ids or [])).all():
        members = list(p.member_emails_json or [])
        if row.interviewer_email not in [m.lower() for m in members]:
            p.member_emails_json = [*members, row.interviewer_email]
            added.append(p.name)
    db.commit()
    log_action(db, "employee", e.id, "made_interviewer", actor[:50], {"pools": added, "skills": skills, "email": row.interviewer_email})
    return {"email": row.interviewer_email, "pools": added, "availability_id": str(row.id)}


def remove_interviewer(db: Session, tenant, e: Employee, *, actor: str) -> dict:
    from app.employees.roles import remove_roles

    addr = _address(db, e)
    removed = []
    for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id).all():
        members = [m for m in (p.member_emails_json or []) if str(m).lower() != addr]
        if len(members) != len(p.member_emails_json or []):
            p.member_emails_json = members
            removed.append(p.name)
    user = db.get(User, e.user_id) if e.user_id else None
    if user is not None:
        remove_roles(db, tenant, user, ["Interviewer"])
    db.commit()
    log_action(db, "employee", e.id, "interviewer_removed", actor[:50], {"pools": removed})
    return {"pools": removed}


def auto_rule_matches(db: Session, tenant, designation: Optional[str], department: Optional[str]) -> bool:
    for rule in _setting(db, tenant, "employees.interviewer.auto_rules") or []:
        if not isinstance(rule, dict) or not rule.get("contains"):
            continue
        value = {"designation": designation, "department": department}.get(rule.get("field") or "designation") or ""
        if str(rule["contains"]).lower() in value.lower():
            return True
    return False


def pools_view(db: Session, tenant, e: Optional[Employee] = None) -> dict:
    addr = _address(db, e) if e is not None else None
    pools = db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.active.is_(True)).order_by(InterviewerPool.name).all()
    row = availability_for(db, tenant, e) if e is not None else None
    return {"pools": [{"id": str(p.id), "name": p.name, "skills": p.skills_json or [], "member": bool(addr and addr in [str(m).lower() for m in (p.member_emails_json or [])])}
                      for p in pools],
            "availability": {"email": row.interviewer_email, "skills": row.skills_json or [], "max_per_day": row.max_interviews_per_day} if row else None}


# ---- link existing interviewers ----


def link_existing(db: Session, tenant, *, actor: str = "system") -> dict:
    """Availability rows without an employee: match by email (company, personal, or the login's email); otherwise one
    HR to-do per address to link or create the employee."""
    from app.models.intelligence import AgentSuggestion

    linked, todo = [], []
    for row in db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id, InterviewerAvailability.employee_id.is_(None)).all():
        addr = (row.interviewer_email or "").strip().lower()
        e = (db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id,
                                       (func.lower(Employee.company_email) == addr) | (func.lower(Employee.personal_email) == addr)).first())
        if e is None:
            u = db.query(User).filter(func.lower(User.email) == addr).first()
            e = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == u.id).first() if u is not None else None
        if e is not None:
            row.employee_id = e.id
            linked.append(addr)
            for s in db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "interviewer_link",
                                                      AgentSuggestion.status == "pending").all():
                if (s.payload_json or {}).get("email") == addr:
                    s.status = "approved"
            continue
        exists = [s for s in db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "interviewer_link",
                                                                AgentSuggestion.status == "pending").all() if (s.payload_json or {}).get("email") == addr]
        if not exists:
            db.add(AgentSuggestion(tenant_id=tenant.tenant_id, agent="onboarding", kind="interviewer_link", entity_type="interviewer_availability", entity_id=row.id,
                                   title=f"Link interviewer {row.interviewer_name or addr} ({addr}) to an employee, or add them as one",
                                   reviewer_permission="core_hr.employee.edit", payload_json={"email": addr, "name": row.interviewer_name, "availability_id": str(row.id)}))
            todo.append(addr)
    db.commit()
    if linked or todo:
        log_action(db, "interviewer_availability", None, "interviewers_linked", actor[:50], {"linked": linked, "todo": todo})
    return {"linked": linked, "todo": todo}


def link_to(db: Session, tenant, availability_id, employee_id, *, actor: str) -> dict:
    """HR resolves the to-do: this interviewer is that employee."""
    from app.models.intelligence import AgentSuggestion

    row = db.get(InterviewerAvailability, availability_id)
    e = db.get(Employee, employee_id)
    if row is None or e is None or row.tenant_id != tenant.tenant_id or e.tenant_id != tenant.tenant_id:
        raise InterviewerError("Not found.")
    row.employee_id = e.id
    for s in db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "interviewer_link",
                                              AgentSuggestion.entity_id == row.id, AgentSuggestion.status == "pending").all():
        s.status = "approved"
    db.commit()
    log_action(db, "employee", e.id, "interviewer_linked", actor[:50], {"email": row.interviewer_email})
    return {"email": row.interviewer_email, "employee_id": str(e.id)}
