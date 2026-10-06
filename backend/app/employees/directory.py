"""Part 20.1: the Employees list and profile.

One row per employee who has finished onboarding (status active / on_notice / exited / absconded and the
older inactive / terminated); pre-hires are still on the Onboarding page. Experience is derived:
- in company   = today (or the exit date) - joined on
- overall      = previous experience (from the resume at hire; HR can edit) + in company
App account: Active / Invited (never set a password) / Disabled / none. Roles: the person's app roles,
plus "Manager" when someone reports to them and "Interviewer" when they are in an interviewer pool or
have interview availability.
"""

import io
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import Department, Employee, EmploymentRecord, Location
from app.models.user import User

LISTED = ("active", "on_notice", "exited", "absconded", "inactive", "terminated", "rehire_eligible")
STATUS_GROUP = {"active": "active", "on_notice": "notice", "exited": "exited", "inactive": "exited", "terminated": "exited",
                "rehire_eligible": "exited", "absconded": "absconded"}


def _today() -> date:
    return date.today()


def months_between(start: Optional[date], end: Optional[date] = None) -> Optional[int]:
    if start is None:
        return None
    end = end or _today()
    m = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    return max(0, m)


def experience_text(months: Optional[int]) -> str:
    if months is None:
        return ""
    y, m = divmod(months, 12)
    parts = ([f"{y} yr{'s' if y != 1 else ''}"] if y else []) + ([f"{m} mth{'s' if m != 1 else ''}"] if m or not y else [])
    return " ".join(parts)


def current_record(db: Session, employee_id) -> Optional[EmploymentRecord]:
    return (db.query(EmploymentRecord).filter(EmploymentRecord.employee_id == employee_id, EmploymentRecord.effective_to.is_(None))
            .order_by(EmploymentRecord.effective_from.desc()).first()
            or db.query(EmploymentRecord).filter(EmploymentRecord.employee_id == employee_id).order_by(EmploymentRecord.effective_from.desc()).first())


def name_of(e: Optional[Employee]) -> str:
    if e is None:
        return ""
    return " ".join(p for p in (e.first_name, e.last_name) if p) or e.employee_code


def app_account(db: Session, user: Optional[User]) -> str:
    if user is None:
        return "none"
    if user.deactivated_at is not None:
        return "disabled"
    return "active" if user.password_set_at else "invited"


def _role_map(db: Session, tenant, user_ids: list) -> dict:
    from app.models.iam import Role, RoleAssignment

    if not user_ids:
        return {}
    names = {r.id: r.name for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id).all()}
    out: dict = {}
    for a in db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id.in_(user_ids)).all():
        out.setdefault(a.user_id, set()).add(names.get(a.role_id, ""))
    return out


def _interviewer_emails(db: Session, tenant) -> set:
    """Everyone who interviews: in a pool, or with availability saved."""
    from app.models.interviewer_availability import InterviewerAvailability
    from app.models.interviewer_pool import InterviewerPool

    emails = {(r.interviewer_email or "").lower() for r in db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id).all()}
    for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.active.is_(True)).all():
        emails |= {str(m).lower() for m in (p.member_emails_json or [])}
    return {e for e in emails if e}


def rows(db: Session, tenant, *, q: Optional[str] = None, department_id: Optional[str] = None, location_id: Optional[str] = None,
         status: Optional[str] = None, joined_from: Optional[date] = None, joined_to: Optional[date] = None, role: Optional[str] = None,
         ids: Optional[list] = None) -> list[dict]:
    emps = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(LISTED))
    if ids:
        emps = emps.filter(Employee.id.in_(ids))
    emps = emps.all()
    deps = {d.id: d.name for d in db.query(Department).filter(Department.tenant_id == tenant.tenant_id).all()}
    locs = {loc.id: loc.name for loc in db.query(Location).filter(Location.tenant_id == tenant.tenant_id).all()}
    by_id = {e.id: e for e in db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).all()}
    users = {u.id: u for u in db.query(User).filter(User.id.in_([e.user_id for e in emps if e.user_id])).all()} if emps else {}
    roles = _role_map(db, tenant, list(users))
    records = {e.id: current_record(db, e.id) for e in emps}
    managers = {r.manager_employee_id for r in records.values() if r is not None and r.manager_employee_id}
    interviewers = _interviewer_emails(db, tenant)
    out = []
    for e in emps:
        r = records.get(e.id)
        user = users.get(e.user_id) if e.user_id else None
        joined = e.joined_on or (r.effective_from if r is not None else None)
        end = e.exited_on if STATUS_GROUP.get(e.status) in ("exited", "absconded") and e.exited_on else None
        in_company = months_between(joined, end)
        prev = e.previous_experience_months
        role_names = sorted(n for n in roles.get(e.user_id, set()) if n)
        if e.id in managers and "Manager" not in role_names:
            role_names.append("Manager")
        emails = {(e.company_email or "").lower(), (user.email.lower() if user else "")}
        if emails & interviewers and "Interviewer" not in role_names:
            role_names.append("Interviewer")
        row = {
            "id": str(e.id), "employee_code": e.employee_code, "name": name_of(e), "first_name": e.first_name, "last_name": e.last_name,
            "designation": r.designation if r else None, "department": deps.get(r.department_id) if r and r.department_id else None,
            "department_id": str(r.department_id) if r and r.department_id else None,
            "manager": name_of(by_id.get(r.manager_employee_id)) if r and r.manager_employee_id else None,
            "manager_id": str(r.manager_employee_id) if r and r.manager_employee_id else None,
            "location": locs.get(r.location_id) if r and r.location_id else None, "location_id": str(r.location_id) if r and r.location_id else None,
            "joined_on": joined.isoformat() if joined else None,
            "experience_company_months": in_company, "experience_company": experience_text(in_company),
            "previous_experience_months": prev,
            "experience_total_months": (prev or 0) + (in_company or 0) if (prev is not None or in_company is not None) else None,
            "experience_total": experience_text((prev or 0) + (in_company or 0)) if (prev is not None or in_company is not None) else "",
            "company_email": e.company_email, "company_email_test": e.company_email_provider == "test",
            "phone": e.personal_phone, "personal_email": e.personal_email, "employment_type": r.employment_type if r else None,
            "status": STATUS_GROUP.get(e.status, "active"), "raw_status": e.status, "exited_on": e.exited_on.isoformat() if e.exited_on else None,
            "app_account": app_account(db, user), "login": user.email if user else None, "user_id": str(user.id) if user else None,
            "roles": role_names, "rehire_eligible": e.rehire_eligible, "demo": (e.custom_fields or {}).get("demo") is True,
        }
        out.append(row)
    if q:
        needle = q.strip().lower()
        out = [x for x in out if any(needle in str(x.get(k) or "").lower() for k in ("name", "employee_code", "designation", "department",
                                                                                   "company_email", "phone", "personal_email", "location"))]
    if department_id:
        out = [x for x in out if x["department_id"] == department_id]
    if location_id:
        out = [x for x in out if x["location_id"] == location_id]
    if status:
        out = [x for x in out if x["status"] == status]
    if joined_from:
        out = [x for x in out if x["joined_on"] and x["joined_on"] >= joined_from.isoformat()]
    if joined_to:
        out = [x for x in out if x["joined_on"] and x["joined_on"] <= joined_to.isoformat()]
    if role:
        out = [x for x in out if role in x["roles"]]
    out.sort(key=lambda x: x["employee_code"] or "")
    return out


def facets(db: Session, tenant) -> dict:
    return {"departments": [{"id": str(d.id), "name": d.name} for d in db.query(Department).filter(Department.tenant_id == tenant.tenant_id).order_by(Department.name)],
            "locations": [{"id": str(loc.id), "name": loc.name} for loc in db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name)],
            "statuses": ["active", "notice", "exited", "absconded"],
            "roles": ["Employee", "Interviewer", "Manager", "HR Admin", "Recruiter", "Hiring Manager", "Super Admin"]}


EXPORT_COLUMNS = (("employee_code", "Employee ID"), ("name", "Name"), ("designation", "Designation"), ("department", "Department"),
                  ("manager", "Manager"), ("location", "Location"), ("joined_on", "Joined on"), ("experience_company", "Experience in company"),
                  ("experience_total", "Overall experience"), ("company_email", "Company email"), ("phone", "Phone"),
                  ("employment_type", "Employment type"), ("status", "Status"), ("app_account", "App account"), ("roles", "Roles"))


def export_xlsx(items: list[dict], columns: Optional[list[str]] = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    cols = [c for c in EXPORT_COLUMNS if not columns or c[0] in columns]
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append([label for _, label in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for x in items:
        ws.append([", ".join(x[k]) if isinstance(x.get(k), list) else (x.get(k) if x.get(k) is not None else "") for k, _ in cols])
    for i, (_, label) in enumerate(cols, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, len(label) + 4)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- Employee ID format ----

SEQ_KEY = "core_hr.employee_code"


def id_format(db: Session, tenant) -> dict:
    from app.models.metadata import Sequence

    row = db.query(Sequence).filter(Sequence.tenant_id == tenant.tenant_id, Sequence.key == SEQ_KEY).first()
    pattern = row.pattern if row else "EMP-{SEQ:5}"
    prefix, _, rest = pattern.partition("{SEQ:")
    padding = int(rest.rstrip("}")) if rest.rstrip("}").isdigit() else 5
    current = row.current if row else 0
    nxt = f"{prefix}{str(current + 1).zfill(padding)}"
    return {"prefix": prefix, "padding": padding, "pattern": pattern, "last_number": current, "next_id": nxt}


def set_id_format(db: Session, tenant, *, prefix: str, padding: int, actor: str) -> dict:
    """Changes how NEW IDs look. The running number carries on (an ID is never reused) and existing IDs
    never change."""
    import re

    from app.audit.service import log_action
    from app.models.metadata import Sequence
    from app.platform.metadata.sequences import define

    prefix = prefix.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-/]{0,12}", prefix):
        raise ValueError("Use up to 12 letters, digits, - _ or / for the prefix.")
    if not 1 <= padding <= 8:
        raise ValueError("The number can have 1 to 8 digits.")
    pattern = f"{prefix}{{SEQ:{padding}}}"
    row = db.query(Sequence).filter(Sequence.tenant_id == tenant.tenant_id, Sequence.key == SEQ_KEY).first()
    before = row.pattern if row else None
    if row is None:
        define(db, tenant, key=SEQ_KEY, pattern=pattern, reset="never")
    else:
        row.pattern = pattern
        db.commit()
    log_action(db, "setting", None, "employee_id_format_changed", actor[:50], {"before": before, "after": pattern})
    return id_format(db, tenant)


def employee_or_none(db: Session, tenant, employee_id: UUID) -> Optional[Employee]:
    e = db.get(Employee, employee_id)
    return e if e is not None and e.tenant_id == tenant.tenant_id else None


# ---- profile (Personal / Job / Documents / Assets / History) ----


def profile(db: Session, tenant, e: Employee) -> dict:
    from app.core_hr.employees import masked_aadhaar
    from app.models.audit_log import AuditLog as Log
    from app.models.core_hr import EmployeeDocument, LetterRecord
    from app.models.onboarding import PreboardingCase, PreboardingDocument
    from app.models.service_desk import Asset, AssetAllocation

    row = (rows(db, tenant, ids=[e.id]) or [None])[0] or {}
    contacts = e.emergency_contacts_json or []
    personal = {
        "first_name": e.first_name, "last_name": e.last_name, "preferred_name": e.preferred_name, "dob": e.dob.isoformat() if e.dob else None,
        "gender": e.gender, "personal_email": e.personal_email, "phone": e.personal_phone, "addresses": e.addresses_json or [],
        "emergency_contacts": contacts, "pan": "XXXXXX" + "****" if e.pan_secret_ref else None, "aadhaar": masked_aadhaar(e),
        "bank_account": "XXXX (masked)" if e.bank_account_secret_ref else None,
    }
    jd = (e.custom_fields or {}).get("joining_details") or {}
    if jd:  # what the joiner gave on the welcome portal (masked values only)
        personal["joining_details"] = jd
    records = (db.query(EmploymentRecord).filter(EmploymentRecord.employee_id == e.id).order_by(EmploymentRecord.effective_from.desc()).all())
    case = db.query(PreboardingCase).filter(PreboardingCase.employee_id == e.id).order_by(PreboardingCase.created_at.desc()).first()
    docs = [{"kind": "document", "id": str(d.id), "label": d.type.replace("_", " ").capitalize(), "date": d.created_at.isoformat() if d.created_at else None,
             "expiry": d.expiry_date.isoformat() if d.expiry_date else None}
            for d in db.query(EmployeeDocument).filter(EmployeeDocument.employee_id == e.id).all()]
    docs += [{"kind": "letter", "id": str(x.id), "label": x.template_key.replace("_", " ").capitalize(), "date": x.generated_at.isoformat() if x.generated_at else None}
             for x in db.query(LetterRecord).filter(LetterRecord.employee_id == e.id).all()]
    if case is not None:
        docs += [{"kind": "joining", "id": str(d.id), "label": d.document_type_code.replace("_", " ").capitalize(), "status": d.verification_status,
                  "date": d.uploaded_at.isoformat() if d.uploaded_at else None}
                 for d in db.query(PreboardingDocument).filter(PreboardingDocument.case_id == case.id).all()]
    assets = []
    for al in db.query(AssetAllocation).filter(AssetAllocation.employee_id == e.id).order_by(AssetAllocation.allocated_at.desc()).all():
        a = db.get(Asset, al.asset_id)
        assets.append({"allocation_id": str(al.id), "asset_id": str(al.asset_id), "tag": a.asset_tag if a else "", "name": a.name if a else "",
                       "category_code": a.category_code if a else None, "given_on": al.allocated_at.isoformat() if al.allocated_at else None,
                       "returned_on": al.returned_at.isoformat() if al.returned_at else None, "condition": al.return_condition,
                       "acknowledged": bool(al.acknowledged_at)})
    ids = [e.id] + ([case.id] if case is not None else []) + ([e.candidate_id] if e.candidate_id else [])
    history = [{"at": h.created_at.isoformat() if h.created_at else None, "action": h.action, "actor": h.actor, "details": h.details}
               for h in db.query(Log).filter(Log.entity_id.in_(ids)).order_by(Log.created_at.desc()).limit(200).all()]
    history += [{"at": r.created_at.isoformat() if r.created_at else r.effective_from.isoformat(), "action": f"job_{r.event_type}", "actor": r.created_by,
                 "details": {"designation": r.designation, "effective_from": r.effective_from.isoformat(), "reason": r.event_reason}} for r in records]
    history.sort(key=lambda h: h["at"] or "", reverse=True)
    return {
        **row, "personal": personal,
        "job": {"designation": row.get("designation"), "department": row.get("department"), "department_id": row.get("department_id"),
                "manager": row.get("manager"), "manager_id": row.get("manager_id"), "location": row.get("location"), "location_id": row.get("location_id"),
                "employment_type": row.get("employment_type"), "joined_on": row.get("joined_on"), "notice_period_days": records[0].notice_period_days if records else None,
                "grade": records[0].grade if records else None, "work_mode": records[0].work_mode if records else None},
        "documents": docs, "assets": assets, "history": history,
        "case_id": str(case.id) if case is not None else None, "candidate_id": str(e.candidate_id) if e.candidate_id else None,
    }
