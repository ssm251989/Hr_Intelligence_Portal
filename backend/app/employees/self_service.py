"""Part 20.3: employee self-service -- the signed-in employee's own data only.

- My profile: personal + job details (job read-only), documents & letters, assets; "Request a change" for the
  personal details below -> HR approves (then it is applied) or rejects, with a note. Nothing changes until HR approves.
- Resignation: the Manager -> HR order from `employees.exit.approval_steps` (default ["manager", "hr"]). The
  employee's manager approves first (optional retention note); HR then confirms the last working day. The
  employee sees Submitted / Manager approved / HR approved - last day <date> / Withdrawn, and can withdraw
  before HR approves.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.change_request import EmployeeChangeRequest
from app.models.core_hr import Employee
from app.models.service_desk import Separation
from app.models.user import User

# what an employee may ask to change (everything else: HR edits it)
FIELDS = ("preferred_name", "pronouns", "personal_email", "phone", "marital_status", "blood_group", "address", "emergency_contact")
OPEN = ("submitted", "retention", "approved", "clearance")


class SelfServiceError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def me(db: Session, tenant, user: User) -> Optional[Employee]:
    return db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---- profile values ----


def _current(e: Employee) -> dict:
    addr = next((a for a in (e.addresses_json or []) if isinstance(a, dict)), {}) or {}
    contact = next((c for c in (e.emergency_contacts_json or []) if isinstance(c, dict)), {}) or {}
    return {"preferred_name": e.preferred_name, "pronouns": e.pronouns, "personal_email": e.personal_email, "phone": e.personal_phone,
            "marital_status": e.marital_status, "blood_group": e.blood_group,
            "address": addr.get("line") or addr.get("address") or ", ".join(str(v) for k, v in addr.items() if v and k not in ("type", "kind")) or None,
            "emergency_contact": {"name": contact.get("name"), "relation": contact.get("relation"), "phone": contact.get("phone")} if contact else None}


def _apply(e: Employee, field: str, value) -> None:
    if field == "phone":
        e.personal_phone = value
    elif field == "address":
        rest = [a for a in (e.addresses_json or []) if not (isinstance(a, dict) and a.get("type") in (None, "current"))]
        e.addresses_json = [{"type": "current", "line": value}, *rest] if value else rest
    elif field == "emergency_contact":
        rest = list(e.emergency_contacts_json or [])[1:]
        e.emergency_contacts_json = ([value] + rest) if value else rest
    else:
        setattr(e, field, value)


def _clean(field: str, value):
    if field == "emergency_contact":
        if not isinstance(value, dict):
            return None
        v = {k: (str(value.get(k) or "").strip()[:120] or None) for k in ("name", "relation", "phone")}
        return v if any(v.values()) else None
    v = str(value or "").strip()[:300] or None
    if field == "personal_email" and v and ("@" not in v or " " in v):
        raise SelfServiceError("That personal email doesn't look right.")
    if field == "phone" and v and sum(ch.isdigit() for ch in v) < 8:
        raise SelfServiceError("That phone number looks too short.")
    return v


# ---- change requests ----


def _cr_dict(r: EmployeeChangeRequest) -> dict:
    return {"id": str(r.id), "employee_id": str(r.employee_id), "changes": r.changes_json or {}, "note": r.note, "status": r.status,
            "requested_by": r.requested_by, "created_at": r.created_at.isoformat() if r.created_at else None, "reviewed_by": r.reviewed_by,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None, "review_note": r.review_note}


def request_change(db: Session, tenant, user: User, changes: dict, note: Optional[str]) -> dict:
    e = me(db, tenant, user)
    if e is None:
        raise SelfServiceError("Your login isn't linked to an employee record yet - ask HR.")
    now = _current(e)
    diff = {}
    for field, value in (changes or {}).items():
        if field not in FIELDS:
            continue
        new = _clean(field, value)
        if new != now.get(field):
            diff[field] = {"old": now.get(field), "new": new}
    if not diff:
        raise SelfServiceError("Nothing changed.")
    r = EmployeeChangeRequest(tenant_id=tenant.tenant_id, employee_id=e.id, requested_by=user.email, changes_json=diff, note=(note or "").strip()[:1000] or None)
    db.add(r)
    db.commit()
    log_action(db, "employee", e.id, "profile_change_requested", user.email[:50], {"fields": sorted(diff)})
    return _cr_dict(r)


def cancel_change(db: Session, tenant, user: User, request_id) -> dict:
    e = me(db, tenant, user)
    r = db.get(EmployeeChangeRequest, request_id)
    if e is None or r is None or r.tenant_id != tenant.tenant_id or r.employee_id != e.id:
        raise SelfServiceError("That request doesn't exist.")
    if r.status != "pending":
        raise SelfServiceError("Only a waiting request can be cancelled.")
    r.status = "cancelled"
    db.commit()
    return _cr_dict(r)


def pending_requests(db: Session, tenant, employee_id=None) -> list[dict]:
    from app.employees.directory import name_of

    q = db.query(EmployeeChangeRequest).filter(EmployeeChangeRequest.tenant_id == tenant.tenant_id, EmployeeChangeRequest.status == "pending")
    if employee_id is not None:
        q = q.filter(EmployeeChangeRequest.employee_id == employee_id)
    out = []
    for r in q.order_by(EmployeeChangeRequest.created_at).all():
        e = db.get(Employee, r.employee_id)
        out.append({**_cr_dict(r), "employee_name": name_of(e), "employee_code": e.employee_code if e else None})
    return out


def review(db: Session, tenant, request_id, *, approve: bool, note: Optional[str], actor: str) -> dict:
    r = db.get(EmployeeChangeRequest, request_id)
    if r is None or r.tenant_id != tenant.tenant_id:
        raise SelfServiceError("That request doesn't exist.")
    if r.status != "pending":
        raise SelfServiceError("This request was already handled.")
    if not approve and not (note or "").strip():
        raise SelfServiceError("Say why, so the employee knows what to do.")
    e = db.get(Employee, r.employee_id)
    if approve:
        for field, ch in (r.changes_json or {}).items():
            if field in FIELDS:
                _apply(e, field, ch.get("new"))
    r.status = "approved" if approve else "rejected"
    r.reviewed_by, r.reviewed_at, r.review_note = actor[:120], _now(), (note or "").strip()[:1000] or None
    db.commit()
    log_action(db, "employee", e.id, "profile_change_approved" if approve else "profile_change_rejected", actor[:50],
               {"fields": sorted(r.changes_json or {}), "note": r.review_note})
    _tell_employee(db, tenant, e, r)
    return _cr_dict(r)


def _tell_employee(db: Session, tenant, e: Employee, r: EmployeeChangeRequest) -> None:
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    user = db.get(User, e.user_id) if e.user_id else None
    to = [a for a in (user.email if user else None, ) if a]
    if not to:
        return
    try:
        send_default(db, tenant, "employee.profile_change_result", to=to, purpose="email.outbound.hr_letters", related_entity_type="employee",
                     related_entity_id=e.id, ctx={"first_name": e.preferred_name or e.first_name,
                                                  "result": "approved and saved" if r.status == "approved" else "not approved",
                                                  "note": r.review_note or "-", "link": f"{public_app_url(db)}/me"})
    except Exception:  # noqa: BLE001 -- the result is on their profile page anyway
        pass


# ---- the employee's own view ----


def status_label(s: Optional[Separation]) -> Optional[dict]:
    if s is None:
        return None
    if s.status == "withdrawn":
        key = "withdrawn"
    elif s.status == "completed":
        key = "completed"
    elif s.status in ("approved", "clearance"):
        key = "hr_approved"
    elif s.manager_approved_at is not None:
        key = "manager_approved"
    else:
        key = "submitted"
    return {"key": key, "last_working_day": s.approved_lwd.isoformat() if s.approved_lwd else None,
            "manager_approved_at": s.manager_approved_at.isoformat() if s.manager_approved_at else None,
            "can_withdraw": s.status in ("submitted", "retention"), "early_release_requested": bool(s.early_release_requested),
            "has_letter": bool(s.resignation_letter_ref)}


def my_profile(db: Session, tenant, user: User) -> dict:
    from app.employees import directory
    from app.platform.iam.authz import effective_permissions

    e = me(db, tenant, user)
    if e is None:
        return {"linked": False}
    p = directory.profile(db, tenant, e)
    p.pop("history", None)
    p.pop("case_id", None)
    p.pop("candidate_id", None)
    s = (db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == e.id)
         .order_by(Separation.created_at.desc()).first())
    perms = effective_permissions(db, tenant, user)
    mine = (db.query(EmployeeChangeRequest).filter(EmployeeChangeRequest.tenant_id == tenant.tenant_id, EmployeeChangeRequest.employee_id == e.id)
            .order_by(EmployeeChangeRequest.created_at.desc()).limit(20).all())
    return {"linked": True, "profile": p, "editable": _current(e), "fields": list(FIELDS), "change_requests": [_cr_dict(r) for r in mine],
            "exit": status_label(s) if s is not None and s.status != "withdrawn" else None,
            "can_resign": "separation.self.create" in perms, "is_interviewer": "Interviewer" in (p.get("roles") or [])}


# ---- resignation: Manager -> HR ----


def steps(db: Session, tenant) -> list[str]:
    v = _setting(db, tenant, "employees.exit.approval_steps")
    return [x for x in (v if isinstance(v, list) else ["manager", "hr"]) if x in ("manager", "hr")] or ["hr"]


def manager_of(db: Session, e: Employee) -> Optional[User]:
    from app.employees.directory import current_record

    r = current_record(db, e.id)
    boss = db.get(Employee, r.manager_employee_id) if r is not None and r.manager_employee_id else None
    u = db.get(User, boss.user_id) if boss is not None and boss.user_id else None
    return u if u is not None and u.deactivated_at is None else None


def needs_manager(db: Session, tenant, s: Separation) -> Optional[User]:
    """The manager who still has to approve this resignation, or None."""
    if s.separation_type != "resignation" or s.manager_approved_at is not None or s.status not in ("submitted", "retention"):
        return None
    if "manager" not in steps(db, tenant):
        return None
    e = db.get(Employee, s.employee_id)
    if e is None or not e.user_id:
        return None
    resigner = db.get(User, e.user_id)
    if resigner is None or (s.initiated_by or "").lower() != resigner.email.lower():  # recorded by HR -> HR decides directly
        return None
    return manager_of(db, e)


def manager_approve(db: Session, tenant, s: Separation, user: User, *, note: Optional[str]) -> Separation:
    boss = needs_manager(db, tenant, s)
    if boss is None:
        raise SelfServiceError("This resignation isn't waiting for a manager.")
    if boss.id != user.id:
        raise SelfServiceError("Only the employee's manager can approve this step.")
    s.manager_approved_at, s.manager_approved_by = _now(), user.email[:120]
    s.manager_note = (note or "").strip()[:2000] or None
    if s.status == "retention":
        s.status = "submitted"
    db.commit()
    log_action(db, "separation", s.id, "manager_approved_resignation", user.email[:50], {"note": s.manager_note})
    return s


def team_exits(db: Session, tenant, user: User) -> list[dict]:
    """Resignations waiting for this manager."""
    from app.employees.directory import name_of

    out = []
    for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status.in_(("submitted", "retention")),
                                         Separation.manager_approved_at.is_(None)).all():
        boss = needs_manager(db, tenant, s)
        if boss is not None and boss.id == user.id:
            e = db.get(Employee, s.employee_id)
            out.append({"id": str(s.id), "employee_name": name_of(e), "employee_code": e.employee_code if e else None,
                        "submitted_on": s.submitted_on.isoformat() if s.submitted_on else None,
                        "requested_lwd": s.requested_lwd.isoformat() if s.requested_lwd else None, "reason_text": s.reason_text,
                        "early_release_requested": bool(s.early_release_requested)})
    return out


def notify_manager(db: Session, tenant, s: Separation) -> None:
    from app.employees.directory import name_of
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    boss = needs_manager(db, tenant, s)
    e = db.get(Employee, s.employee_id)
    if boss is None or e is None:
        return
    if (e.custom_fields or {}).get("demo"):  # demo employees never email real staff
        boss_emp = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == boss.id).first()
        if not (boss_emp is not None and (boss_emp.custom_fields or {}).get("demo")):
            return
    try:
        send_default(db, tenant, "employee.resignation_to_manager", to=[boss.email], purpose="email.outbound.hr_letters", related_entity_type="separation",
                     related_entity_id=s.id, ctx={"name": name_of(e), "requested": s.requested_lwd.strftime("%d %b %Y") if s.requested_lwd else "not given",
                                                  "early": "Yes" if s.early_release_requested else "No", "link": f"{public_app_url(db)}/exits?approve={s.id}"})
    except Exception:  # noqa: BLE001 -- it's also on their Home to-do list
        pass


def withdraw_mine(db: Session, tenant, user: User) -> Separation:
    from app.service_desk import separations

    e = me(db, tenant, user)
    s = (db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == e.id, Separation.status.in_(OPEN))
         .order_by(Separation.created_at.desc()).first()) if e is not None else None
    if s is None:
        raise SelfServiceError("You don't have a resignation in progress.")
    if s.status not in ("submitted", "retention"):
        raise SelfServiceError("HR has already approved your last working day - please talk to HR to withdraw.")
    separations.withdraw(db, s, actor=user.email)
    log_action(db, "separation", s.id, "withdrawn_by_employee", user.email[:50], {})
    return s


# ---- HR starts an exit from the Employees list ----

START_KINDS = {"resigned": "resignation", "terminated": "termination", "absconded": "absconding", "retirement": "retirement", "contract_end": "contract_end"}


def start_exit(db: Session, tenant, employee_id, *, kind: str, last_working_day, notes: str, confirm_now: bool, send_notice: bool,
               actor: str, actor_user_id=None) -> Separation:
    """HR records an exit (no manager step - HR decides). Optionally confirms the last working day straight away
    (-> the exit checklist starts) and, for absconding, emails the notice to the personal + company email."""
    from datetime import date

    from app.service_desk import separations

    if kind not in START_KINDS:
        raise SelfServiceError("Choose the type of exit.")
    if len((notes or "").strip()) < 3:
        raise SelfServiceError("Please add a short note (what happened, who was told).")
    e = db.get(Employee, employee_id)
    if e is None or e.tenant_id != tenant.tenant_id:
        raise SelfServiceError("That employee doesn't exist.")
    if kind == "absconded" and last_working_day > date.today():
        raise SelfServiceError("For absconding, the last working day is the last day they actually came in (today or earlier).")
    try:
        s = separations.initiate(db, tenant, employee_id=e.id, separation_type=START_KINDS[kind], actor=actor, actor_user_id=actor_user_id,
                                 submitted_on=min(date.today(), last_working_day), requested_lwd=last_working_day, reason_text=notes.strip()[:2000])
        if s.status == "retention":  # HR recorded it -- not a request to talk them out of
            separations.record_retention(db, s, notes="Exit recorded by HR.", retained=False, actor=actor)
        if confirm_now:
            short = max(0, (separations.standard_lwd(s) - last_working_day).days)
            separations.approve_lwd(db, tenant, s, lwd=last_working_day, actor=actor, waived_days=short)
    except separations.SeparationError as exc:
        raise SelfServiceError(str(exc)) from exc
    s.rehire_eligible = kind in ("resigned", "retirement", "contract_end")
    db.commit()
    log_action(db, "separation", s.id, "exit_started_by_hr", actor[:50], {"kind": kind, "last_working_day": last_working_day.isoformat(), "confirmed": confirm_now})
    if kind == "absconded" and send_notice:
        _absconding_notice(db, tenant, s, e, actor=actor)
    return s


def _absconding_notice(db: Session, tenant, s: Separation, e: Employee, *, actor: str) -> None:
    from app.platform.comms.defaults import send_default

    to = [a for a in dict.fromkeys([e.personal_email, e.company_email]) if a]
    if not to:
        return
    m = send_default(db, tenant, "employee.absconding_notice", to=to, purpose="email.outbound.hr_letters", related_entity_type="separation",
                     related_entity_id=s.id, ctx={"first_name": e.preferred_name or e.first_name,
                                                  "last_seen": s.requested_lwd.strftime("%d %b %Y") if s.requested_lwd else "your last day at work"})
    s.absconding_notices_json = [*(s.absconding_notices_json or []),
                                 {"kind": "absconding_notice", "issued_at": _now().isoformat(), "issued_by": actor, "to": to, "email": getattr(m, "status", None)}]
    db.commit()
    log_action(db, "separation", s.id, "absconding_notice_sent", actor[:50], {"to": to})
