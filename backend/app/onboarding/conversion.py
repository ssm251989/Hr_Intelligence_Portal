"""Pre-hire -> employee conversion (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 4).

On DOJ + an explicit "joined" confirmation: the case's pre_hire employee becomes `active`,
gets its `hire` employment record (Part 7's LifecycleService), a user account with the
Employee role (+ any roles `assignment_rules` add), its onboarding plan and joining letter
chosen by `assignment_rules` (JSONLogic over entity/location/grade/worker_type/department).

Idempotent: converting an already-joined case returns the same employee/user and creates
nothing new -- every step checks for its own prior output first.
"""

import secrets
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.security import hash_password
from app.core_hr import letters as letters_service
from app.core_hr import lifecycle
from app.models.core_hr import Employee, LetterRecord
from app.models.iam import Role, RoleAssignment
from app.models.onboarding import BgvCase, PreboardingCase
from app.models.user import User
from app.onboarding import assignment_rules, plans
from app.platform.iam.roles import bridge_single_user, sync_system_roles
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


class ConversionError(Exception):
    pass


def conversion_context(case: PreboardingCase) -> dict:
    attrs = case.attributes_json or {}
    return {
        "legal_entity_id": attrs.get("legal_entity_id"), "location_id": attrs.get("location_id"),
        "department_id": attrs.get("department_id"), "grade": attrs.get("grade"),
        "worker_type": attrs.get("worker_type", "employee"), "designation": attrs.get("designation"),
        "employment_type": attrs.get("employment_type"), **{k: v for k, v in attrs.items() if k.startswith("cf_")},
    }


def _bgv_blocks(db: Session, tenant: TenantContext, case: PreboardingCase) -> bool:
    if not SettingsService(db).get("onboarding.bgv.block_conversion_until_clear", SettingContext(tenant=tenant)):
        return False
    cases = db.query(BgvCase).filter(BgvCase.tenant_id == tenant.tenant_id, BgvCase.preboarding_case_id == case.id).all()
    return any(c.decision not in ("clear", "accept_with_discrepancy") for c in cases)


def _ensure_user(db: Session, tenant: TenantContext, employee: Employee, case: PreboardingCase) -> User:
    if employee.user_id:
        user = db.get(User, employee.user_id)
        if user is not None:
            return user
    user = db.query(User).filter(User.email == case.email).first()
    if user is None:
        # Unusable random password: the new hire sets their own via the normal reset flow.
        user = User(
            tenant_id=tenant.tenant_id, email=case.email, hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=" ".join(p for p in (employee.first_name, employee.last_name) if p), role="employee",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    bridge_single_user(db, tenant, user)
    employee.user_id = user.id
    db.commit()
    return user


def _assign_rule_roles(db: Session, tenant: TenantContext, user: User, role_names: list[str]) -> list[str]:
    if not role_names:
        return []
    sync_system_roles(db, tenant)
    assigned = []
    for name in role_names:
        role = db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name == name).first()
        if role is None:
            continue  # a rule naming a role this tenant doesn't have is skipped, not fatal
        exists = db.query(RoleAssignment).filter(
            RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user.id, RoleAssignment.role_id == role.id,
        ).first()
        if exists is None:
            db.add(RoleAssignment(tenant_id=tenant.tenant_id, user_id=user.id, role_id=role.id, scope_type="self"))
        assigned.append(name)
    db.commit()
    return assigned


def convert(db: Session, tenant: TenantContext, case: PreboardingCase, *, actor: str, as_of: Optional[date] = None,
            create_account: bool = True) -> dict:
    """Part 20.2: create_account=False -> the Onboarding agent (app/employees/creation.py) makes the app account
    with the COMPANY email after HR approves, instead of a login on the personal email here."""
    today = as_of or datetime.now(timezone.utc).date()
    if case.status in ("revoked", "no_show"):
        raise ConversionError(f"case is {case.status}; it cannot be converted")
    if case.joining_date > today:
        raise ConversionError(f"joining date {case.joining_date.isoformat()} has not arrived yet")
    if case.status != "joined" and _bgv_blocks(db, tenant, case):
        raise ConversionError("background verification has not been cleared")

    employee = db.get(Employee, case.employee_id) if case.employee_id else None
    if employee is None:
        raise ConversionError("case has no pre-hire employee record")

    already_joined = case.status == "joined"
    ctx = conversion_context(case)

    if employee.status == "pre_hire":
        employee.status = "active"
        db.commit()

    if lifecycle.get_current_employment(db, tenant, employee.id, as_of=case.joining_date) is None:
        changes = {k: ctx[k] for k in ("legal_entity_id", "location_id", "department_id", "grade", "designation", "employment_type") if ctx.get(k)}
        lifecycle.apply_event(
            db, tenant, employee_id=employee.id, event_type="hire", effective_from=case.joining_date,
            changes=changes, reason="pre-boarding conversion", created_by=actor,
        )

    user = _ensure_user(db, tenant, employee, case) if create_account else (db.get(User, employee.user_id) if employee.user_id else None)
    roles = ["Employee", *(_assign_rule_roles(db, tenant, user, assignment_rules.resolve_all(db, tenant, "role", ctx)) if user is not None else [])]

    plan_code = assignment_rules.resolve_one(db, tenant, "onboarding_plan_template", ctx) or (
        SettingsService(db).get("onboarding.conversion.default_plan_template", SettingContext(tenant=tenant)) or None
    )
    plan = None
    if plan_code:
        template = plans.get_template(db, tenant, plan_code)
        if template is not None:
            plan = plans.generate_plan(db, tenant, case, template)

    letter_key = assignment_rules.resolve_one(db, tenant, "letter_template", ctx)
    letter_id = None
    if letter_key:
        existing_letter = db.query(LetterRecord).filter(LetterRecord.tenant_id == tenant.tenant_id, LetterRecord.employee_id == employee.id, LetterRecord.template_key == letter_key).first()
        if existing_letter is not None:
            letter_id = existing_letter.id
        else:
            try:
                letter = letters_service.generate_letter(
                    db, tenant, employee_id=employee.id, template_key=letter_key,
                    context={"employee": {"first_name": employee.first_name, "last_name": employee.last_name, "employee_code": employee.employee_code}, "joining_date": case.joining_date.isoformat()},
                    generated_by=actor,
                )
                letter_id = letter.id
            except letters_service.LetterTemplateNotFoundError:
                letter_id = None

    if not already_joined:
        case.status = "joined"
        case.joined_at = datetime.now(timezone.utc)
        case.history_json = [*(case.history_json or []), {"event": "joined", "actor": actor, "at": case.joined_at.isoformat()}]
        db.commit()
        log_action(db, "preboarding_case", case.id, "converted_to_employee", actor, {"employee_id": str(employee.id), "user_id": str(user.id) if user else None})

    return {
        "case_id": str(case.id), "employee_id": str(employee.id), "employee_code": employee.employee_code,
        "user_id": str(user.id) if user else None, "roles": roles, "plan_id": str(plan.id) if plan else None,
        "letter_id": str(letter_id) if letter_id else None, "already_converted": already_joined,
    }
