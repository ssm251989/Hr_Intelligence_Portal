"""Part 20.2: the Onboarding agent turns a joined person into an employee.

Trigger: "Mark as joined" (= onboarding complete; joiner_actions.mark_joined). The agent:
1. looks for an existing employee record -- same candidate or same personal email = the same person (link,
   don't duplicate); same phone, or same name + date of birth = a POSSIBLE match: HR answers "Is this the
   same person as CTD-0007?" on the card before anything is created;
2. prepares the record from candidate + offer + job + joining details (names, designation, department,
   manager, location, joining date, employment type, previous experience, personal email/phone, emergency
   contact, bank/PAN/Aadhaar encrypted and masked);
3. the Employee ID (the pre-hire record's, from the Employee ID format);
4. a company email from the pattern (checked free) -- created through the email-admin connection, or an IT
   to-do "Create mailbox ..." when none is connected;
5. the app account (login = company email, role Employee + roles from the rules) and a "Set your password"
   invite (72 h) to the company and personal email;
6. the person moves to Employees (Active); the onboarding card says "Employee created - CTD-0012".

Settings > Onboarding & employees > "When onboarding completes": `approve` (DEFAULT -- the plan waits as an
approval card HR can edit) or `automatic`. Every step is audited; a failing step (e.g. the mailbox API)
is shown in plain words with Retry, never silent -- steps already done are not repeated.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Department, Employee, Location
from app.models.intelligence import AgentSuggestion
from app.models.onboarding import PreboardingCase
from app.models.user import User

KIND = "employee_create"
TYPES = {"full-time": "full_time", "full time": "full_time", "part-time": "part_time", "part time": "part_time", "contract": "contract",
         "internship": "intern", "intern": "intern", "consultant": "consultant", "freelance": "consultant"}


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _match_by_name(rows, text: Optional[str]):
    t = (text or "").strip().lower()
    if not t:
        return None
    return next((r for r in rows if (r.name or "").strip().lower() == t), None) or next(
        (r for r in rows if t in (r.name or "").lower() or (r.name or "").lower() in t), None)


def role_rules(db: Session, tenant, designation: Optional[str], department: Optional[str]) -> list[str]:
    """Settings: default roles + rules like {"field": "designation", "contains": "interview", "role": "Interviewer"}."""
    roles = list(_setting(db, tenant, "employees.default_roles") or ["Employee"])
    for rule in _setting(db, tenant, "employees.role_rules") or []:
        value = {"designation": designation, "department": department}.get(rule.get("field") or "designation") or ""
        if rule.get("contains") and rule["contains"].lower() in value.lower() and rule.get("role"):
            roles.append(rule["role"])
    from app.employees.interviewers import auto_rule_matches  # Part 20.4: Settings > interviewer auto rule

    if auto_rule_matches(db, tenant, designation, department):
        roles.append("Interviewer")
    return list(dict.fromkeys(["Employee", *roles]))


def find_match(db: Session, tenant, e: Employee, *, candidate_id, personal_email: Optional[str], phone: Optional[str],
               first: str, last: Optional[str], dob: Optional[str]) -> Optional[dict]:
    others = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.id != e.id, Employee.status != "pre_hire").all()
    norm_phone = lambda p: "".join(ch for ch in (p or "") if ch.isdigit())[-10:]  # noqa: E731
    for o in others:
        if candidate_id and o.candidate_id == candidate_id:
            return {"kind": "exact", "employee_id": str(o.id), "code": o.employee_code, "name": _name(o), "reason": "same candidate record"}
        if personal_email and (o.personal_email or "").lower() == personal_email.lower():
            return {"kind": "exact", "employee_id": str(o.id), "code": o.employee_code, "name": _name(o), "reason": "same personal email"}
    for o in others:
        if phone and norm_phone(o.personal_phone) and norm_phone(o.personal_phone) == norm_phone(phone):
            return {"kind": "possible", "employee_id": str(o.id), "code": o.employee_code, "name": _name(o), "reason": "same phone number"}
        if dob and o.dob and o.dob.isoformat() == dob and (o.first_name or "").lower() == (first or "").lower() and (o.last_name or "").lower() == (last or "").lower():
            return {"kind": "possible", "employee_id": str(o.id), "code": o.employee_code, "name": _name(o), "reason": "same name and date of birth"}
    return None


def _name(e: Employee) -> str:
    return " ".join(p for p in (e.first_name, e.last_name) if p)


def gather(db: Session, tenant, case: PreboardingCase) -> dict:
    """Everything the agent will create, as one editable plan."""
    from app.employees import mailboxes
    from app.onboarding import welcome_steps
    from app.onboarding.joiner_actions import _ctx

    application, cand, job, offer = _ctx(db, case)
    e = db.get(Employee, case.employee_id) if case.employee_id else None
    if e is None:
        raise ValueError("This joiner has no pre-hire employee record.")
    jd = welcome_steps._plain(case)
    first = (jd.get("first_name") or e.first_name or (cand.first_name if cand else "") or "").strip()
    last = (jd.get("last_name") or e.last_name or (cand.last_name if cand else "") or "").strip()
    designation = (offer.designation if offer is not None and getattr(offer, "designation", None) else None) or (job.title if job else None)
    deps = db.query(Department).filter(Department.tenant_id == tenant.tenant_id).all()
    locs = db.query(Location).filter(Location.tenant_id == tenant.tenant_id).all()
    dep = _match_by_name(deps, job.department if job else None)
    loc = _match_by_name(locs, (getattr(offer, "work_location", None) if offer is not None else None) or (job.location if job else None))
    manager = None
    if job is not None and job.hiring_manager_id:
        manager = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == job.hiring_manager_id,
                                            Employee.status.in_(("active", "on_notice"))).first()
    years = None
    if cand is not None and isinstance(cand.parsed_fields, dict):
        try:
            years = float(cand.parsed_fields.get("total_experience_years")) if cand.parsed_fields.get("total_experience_years") not in (None, "") else None
        except (TypeError, ValueError):
            years = None
    personal_email = (jd.get("personal_email") or e.personal_email or case.email or (cand.email if cand else "") or "").strip().lower() or None
    phone = jd.get("phone") or e.personal_phone or (cand.phone if cand else None)
    joined_on = case.joining_date.isoformat() if case.joining_date else date.today().isoformat()
    suggestion = mailboxes.suggest(db, tenant, first, last, except_employee_id=e.id)
    match = find_match(db, tenant, e, candidate_id=cand.id if cand else None, personal_email=personal_email, phone=phone, first=first, last=last,
                       dob=jd.get("date_of_birth") or (e.dob.isoformat() if e.dob else None))
    return {
        "case_id": str(case.id), "employee_id": str(e.id), "employee_code": e.employee_code, "candidate_id": str(cand.id) if cand else None,
        "first_name": first, "last_name": last, "preferred_name": jd.get("preferred_name") or e.preferred_name,
        "designation": designation, "department_id": str(dep.id) if dep else None, "department": dep.name if dep else (job.department if job else None),
        "department_matched": dep is not None, "location_id": str(loc.id) if loc else None, "location": loc.name if loc else (job.location if job else None),
        "location_matched": loc is not None, "manager_id": str(manager.id) if manager else None, "manager": _name(manager) if manager else None,
        "joined_on": joined_on, "employment_type": TYPES.get((job.job_type or "").strip().lower(), "full_time") if job else "full_time",
        "previous_experience_months": int(round(years * 12)) if years is not None else None,
        "personal_email": personal_email, "phone": phone,
        "emergency_contact": {k: jd.get(f"emergency_{k}") for k in ("name", "relation", "phone")} if jd.get("emergency_name") else None,
        "has_bank_id": any(jd.get(k) for k in welcome_steps.SENSITIVE),
        "company_email": suggestion["address"], "company_email_tried": suggestion["tried"],
        "email_provider": mailboxes.active_provider(db, tenant) or "it_todo",
        "roles": role_rules(db, tenant, designation, dep.name if dep else (job.department if job else None)),
        "match": match, "job_title": job.title if job else None,
    }


def prepare(db: Session, tenant, case: PreboardingCase, *, actor: str) -> AgentSuggestion:
    """The approval card (one per case; refreshed when prepared again)."""
    plan = gather(db, tenant, case)
    row = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == KIND,
                                            AgentSuggestion.entity_id == case.id).order_by(AgentSuggestion.created_at.desc()).first())
    name = " ".join(p for p in (plan["first_name"], plan["last_name"]) if p)
    title = f"Create employee {plan['employee_code']} - {name}"
    if row is not None and row.status == "pending":
        steps = (row.payload_json or {}).get("steps")
        row.payload_json, row.title = {**plan, "steps": steps} if steps else plan, title
    elif row is None:
        row = AgentSuggestion(tenant_id=tenant.tenant_id, agent="onboarding", kind=KIND, title=title, entity_type="preboarding_case", entity_id=case.id,
                              reviewer_permission="core_hr.employee.edit", payload_json=plan)
        db.add(row)
    db.commit()
    log_action(db, "preboarding_case", case.id, "employee_prepared", actor[:50], {"employee_code": plan["employee_code"], "company_email": plan["company_email"],
                                                                                    "match": plan["match"]})
    return row


def to_dict(s: AgentSuggestion) -> dict:
    p = s.final_payload_json if s.status == "approved" and s.final_payload_json else s.payload_json
    return {"id": str(s.id), "status": s.status, "title": s.title, "plan": p or {}, "created_at": s.created_at.isoformat() if s.created_at else None,
            "reviewed_by": s.reviewed_by, "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None}


EDITABLE = ("first_name", "last_name", "preferred_name", "designation", "department_id", "location_id", "manager_id", "employment_type",
            "joined_on", "previous_experience_months", "company_email", "roles", "personal_email", "phone")


def approve(db: Session, tenant, s: AgentSuggestion, *, edits: Optional[dict], actor: str) -> dict:
    """Runs the plan (HR's edits on top). Idempotent per step: a Retry only redoes what failed."""
    from app.employees import accounts, mailboxes

    if s.kind != KIND or s.status == "rejected":
        raise ValueError("This card is no longer open.")
    plan = {**(s.payload_json or {}), **{k: v for k, v in (edits or {}).items() if k in EDITABLE}}
    match = plan.get("match")
    decision = (edits or {}).get("match_decision")  # "same" | "different"
    if match and match.get("kind") == "possible" and decision not in ("same", "different") and not plan.get("match_decision"):
        raise ValueError(f"Please answer first: is this the same person as {match['code']} ({match['name']})?")
    if decision:
        plan["match_decision"] = decision
    case = db.get(PreboardingCase, plan["case_id"])
    e = db.get(Employee, plan["employee_id"])
    if case is None or e is None:
        raise ValueError("The joiner or their pre-hire record no longer exists.")
    steps = {x["step"]: x for x in plan.get("steps", [])}

    def step(name: str, fn):
        if steps.get(name, {}).get("ok"):
            return steps[name]
        try:
            detail = fn()
            steps[name] = {"step": name, "ok": True, "detail": detail, "at": _now().isoformat()}
        except Exception as exc:  # noqa: BLE001 -- shown on the card in plain words, with Retry
            steps[name] = {"step": name, "ok": False, "error": str(exc)[:300], "at": _now().isoformat()}
        return steps[name]

    # 1. link to an existing record (same person) -- never a duplicate
    if match and (match.get("kind") == "exact" or plan.get("match_decision") == "same"):
        def _link():
            nonlocal e
            old = db.get(Employee, match["employee_id"])
            if old is None:
                return "the matched record no longer exists - kept the new one"
            pre = e
            pre.status = "inactive"
            pre.custom_fields = {**(pre.custom_fields or {}), "merged_into": str(old.id)}
            case.employee_id = old.id
            old.status, old.exited_on = "active", None
            db.commit()
            e = old
            plan["employee_id"], plan["employee_code"] = str(old.id), old.employee_code
            return f"linked to {old.employee_code} (same person); new pre-hire record {pre.employee_code} not used"
        step("link_existing", _link)
        e = db.get(Employee, plan["employee_id"])

    # 2. the record
    def _record():
        from uuid import UUID

        from app.employees.directory import current_record
        from app.models.core_hr import EmploymentRecord
        from app.onboarding import welcome_steps

        e.first_name = plan.get("first_name") or e.first_name
        e.last_name = plan.get("last_name") or e.last_name
        e.preferred_name = plan.get("preferred_name") or e.preferred_name
        e.personal_email = plan.get("personal_email") or e.personal_email
        e.personal_phone = plan.get("phone") or e.personal_phone
        e.joined_on = date.fromisoformat(plan["joined_on"]) if plan.get("joined_on") else e.joined_on
        e.previous_experience_months = plan.get("previous_experience_months")
        e.candidate_id = UUID(plan["candidate_id"]) if plan.get("candidate_id") else e.candidate_id
        if plan.get("emergency_contact"):
            ec = plan["emergency_contact"]
            e.emergency_contacts_json = [{"name": ec.get("name"), "relationship": ec.get("relation"), "phone": ec.get("phone")}]
        if e.status in ("pre_hire", "inactive", "exited", "terminated", "rehire_eligible"):
            e.status = "active"
        r = current_record(db, e.id)
        if r is None:
            r = EmploymentRecord(tenant_id=tenant.tenant_id, employee_id=e.id, effective_from=e.joined_on or date.today(), event_type="hire", created_by=actor[:50])
            db.add(r)
        r.designation = plan.get("designation") or r.designation
        r.department_id = UUID(plan["department_id"]) if plan.get("department_id") else r.department_id
        r.location_id = UUID(plan["location_id"]) if plan.get("location_id") else r.location_id
        r.manager_employee_id = UUID(plan["manager_id"]) if plan.get("manager_id") else r.manager_employee_id
        r.employment_type = plan.get("employment_type") or r.employment_type
        db.commit()
        # bank / PAN / Aadhaar from the joining details -> encrypted on the employee (masked everywhere)
        from app.core_hr.employees import set_encrypted_field

        jd = welcome_steps._plain(case)
        moved = []
        for src, field in (("pan", "pan"), ("aadhaar", "aadhaar"), ("bank_account_number", "bank_account")):
            if jd.get(src) and not getattr(e, f"{field}_secret_ref"):
                set_encrypted_field(db, tenant, e, field, jd[src], created_by=actor[:50])
                moved.append(field)
        return f"record filled ({', '.join(moved) or 'no bank/ID'} stored encrypted)"
    step("employee_record", _record)

    # 3. company email
    def _mailbox():
        address = (plan.get("company_email") or "").strip().lower()
        if not address:
            return "no company email (none chosen)"
        if e.company_email == address:
            return f"{address} already set"
        ok, why = mailboxes.is_free(db, tenant, address, except_employee_id=e.id)
        if not ok:
            raise ValueError(f"{address}: {why}")
        out = mailboxes.create(db, tenant, e, address, joining=plan.get("joined_on"), actor=actor)
        if out.get("temp_password"):
            plan["one_time_password_shown"] = True  # the password itself is never stored -- see approve() return
            plan["_one_time"] = out["temp_password"]
        return ({"provider": out["provider"], "address": address} if out["mode"] == "provider"
                else {"it_todo": out["todo_id"], "address": address, "note": "IT to-do created - the login stays on the personal email until IT confirms"})
    step("company_email", _mailbox)

    # 4. app account + invite
    def _account():
        user = accounts.ensure_account(db, tenant, e, actor=actor, extra_roles=[r for r in (plan.get("roles") or []) if r != "Employee"])
        if "Interviewer" in (plan.get("roles") or []):  # Part 20.4: ready to be picked for interviews (default hours; they edit them)
            from app.employees.interviewers import ensure_availability

            ensure_availability(db, tenant, e, actor=actor)
        inv = accounts.send_invite(db, tenant, e, actor=actor)
        if (inv.get("email_status") or "").startswith("failed"):
            raise ValueError(f"Account {user.email} created, but the invite email failed: {inv['email_status'][8:]}")
        return {"login": user.email, "invite_sent_to": inv["sent_to"]}
    step("app_account", _account)

    one_time = plan.pop("_one_time", None)
    plan["steps"] = list(steps.values())
    all_ok = all(x.get("ok") for x in plan["steps"])
    if all_ok:
        case.attributes_json = {**(case.attributes_json or {}), "employee_created": {"code": e.employee_code, "employee_id": str(e.id),
                                                                                   "at": _now().isoformat(), "by": actor}}
        s.status, s.final_payload_json, s.reviewed_by, s.reviewed_at = "approved", plan, actor[:120], _now()
    s.payload_json = plan
    db.commit()
    log_action(db, "preboarding_case", case.id, "employee_created" if all_ok else "employee_creation_step_failed", actor[:50],
               {"employee_code": e.employee_code, "steps": [{k: v for k, v in x.items() if k != "detail"} for x in plan["steps"]]})
    if all_ok:
        log_action(db, "employee", e.id, "employee_created_by_agent", actor[:50], {"case_id": str(case.id), "company_email": e.company_email})
    return {**to_dict(s), "one_time_password": one_time, "done": all_ok}


def reject(db: Session, tenant, s: AgentSuggestion, *, actor: str, note: Optional[str] = None) -> dict:
    s.status, s.reviewed_by, s.reviewed_at = "rejected", actor[:120], _now()
    s.final_payload_json = {**(s.payload_json or {}), "note": note}
    db.commit()
    log_action(db, "preboarding_case", s.entity_id, "employee_creation_put_off", actor[:50], {"note": note})
    return to_dict(s)


def on_joined(db: Session, tenant, case: PreboardingCase, *, actor: str) -> dict:
    """Called by mark_joined. Approval mode (default): the card waits for HR. Automatic: done now."""
    try:
        s = prepare(db, tenant, case, actor=actor)
    except Exception as exc:  # noqa: BLE001 -- joining itself must not fail because of the agent
        log_action(db, "preboarding_case", case.id, "employee_prepare_failed", actor[:50], {"error": str(exc)[:300]})
        return {"mode": "error", "error": str(exc)[:300]}
    if (_setting(db, tenant, "employees.on_onboarding_complete") or "approve") == "automatic":
        try:
            out = approve(db, tenant, s, edits=None, actor="onboarding agent")
            return {"mode": "automatic", "suggestion_id": str(s.id), "done": out["done"]}
        except ValueError as exc:  # e.g. a possible duplicate: HR must answer -> stays a card
            return {"mode": "approve", "suggestion_id": str(s.id), "waiting": str(exc)}
    return {"mode": "approve", "suggestion_id": str(s.id)}


def pending(db: Session, tenant) -> list[dict]:
    rows = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == KIND,
                                             AgentSuggestion.status == "pending").order_by(AgentSuggestion.created_at).all())
    return [to_dict(s) for s in rows]


def it_todos(db: Session, tenant) -> list[dict]:
    rows = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind.in_(("it_mailbox_create", "it_mailbox_suspend")),
                                             AgentSuggestion.status == "pending").order_by(AgentSuggestion.created_at).all())
    return [{"id": str(s.id), "kind": s.kind, "title": s.title, **(s.payload_json or {})} for s in rows]


def user_of(db: Session, e: Employee) -> Optional[User]:
    return db.get(User, e.user_id) if e.user_id else None
