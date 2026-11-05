"""Part 22.4: Employees > Assign roles -- give / take app roles for one or many employees.

- The roles HR picks from: Employee, Interviewer, Hiring manager, Recruiter, HR, HR Admin, Finance, IT,
  Admin & facilities, plus the company's own (custom) roles. Other system roles someone already has
  (Super Admin, Manager, Auditor, ...) are shown read-only and never touched here.
- Who can: iam.role_assignments.configure (HR Admin and Super Admin by default) -- the spec's "users.manage_roles".
- The last HR Admin can't lose it (also when it's yourself).
- No app account yet -> "Create account and send invite" (accounts.send_invite), then the roles.
- Interviewer: optional skills / pools (interviewers.make_interviewer); removing it takes them out of the pools.
- The legacy users.role column follows (admin / recruiter / hiring_manager / interviewer / employee) so the
  older role-gated pages (e.g. Candidate emails) agree with what was ticked.
- Takes effect on the employee's next page load; optional email "Your access ... was updated"; audit-logged.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Employee
from app.models.iam import Role, RoleAssignment
from app.models.user import User

# (system role name, key used for the label/description in the UI, scope of the assignment)
CATALOG = (
    ("Employee", "employee", "self"),
    ("Interviewer", "interviewer", "self"),
    ("Hiring Manager", "hiring_manager", "all"),
    ("Recruiter", "recruiter", "all"),
    ("HRBP", "hr", "all"),
    ("HR Admin", "hr_admin", "all"),
    ("Finance", "finance", "all"),
    ("IT", "it", "all"),
    ("Admin & facilities", "admin_facilities", "all"),
)
ADMIN_ROLES = ("HR Admin", "Super Admin")


class RoleAdminError(ValueError):
    pass


def catalog(db: Session, tenant) -> list[dict]:
    from app.platform.iam.roles import sync_system_roles

    by_name = sync_system_roles(db, tenant)
    out = [{"id": str(by_name[name].id), "name": name, "key": key, "system": True, "description": None} for name, key, _ in CATALOG if name in by_name]
    for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.is_system.is_(False)).order_by(Role.name).all():
        out.append({"id": str(r.id), "name": r.name, "key": None, "system": False, "description": r.description})
    return out


def _assigned(db: Session, tenant, user_id) -> dict:
    roles = {r.id: r for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id).all()}
    return {a.role_id: roles[a.role_id] for a in db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id,
                                                                                 RoleAssignment.user_id == user_id).all() if a.role_id in roles}


def state(db: Session, tenant, employees: list[Employee]) -> list[dict]:
    from app.employees import directory

    managed = {c["id"] for c in catalog(db, tenant)}
    out = []
    for e in employees:
        user = db.get(User, e.user_id) if e.user_id else None
        held = _assigned(db, tenant, user.id) if user else {}
        out.append({"employee_id": str(e.id), "name": directory.name_of(e), "status": e.status, "has_account": user is not None,
                    "login": user.email if user else None,
                    "role_ids": sorted(str(rid) for rid in held if str(rid) in managed),
                    "other_roles": sorted(r.name for rid, r in held.items() if str(rid) not in managed)})
    return out


def _admins_left(db: Session, tenant, *, without_user=None) -> int:
    ids = [r.id for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name.in_(ADMIN_ROLES)).all()]
    q = (db.query(RoleAssignment.user_id).join(User, User.id == RoleAssignment.user_id)
         .filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.role_id.in_(ids), User.deactivated_at.is_(None)))
    if without_user is not None:
        q = q.filter(RoleAssignment.user_id != without_user)
    return q.distinct().count()


def _legacy_role(names: set[str], current: str) -> str:
    """The old single users.role, kept in step with the ticked roles (older pages still gate on it)."""
    if current == "agency":
        return current
    if names & {"HR Admin", "Super Admin"}:
        return "admin"
    if names & {"HRBP", "Recruiter"}:
        return "recruiter"
    if "Hiring Manager" in names:
        return "hiring_manager"
    if "Interviewer" in names:
        return "interviewer"
    return "employee"


def apply(db: Session, tenant, employees: list[Employee], *, actor: User, set_role_ids: Optional[list[str]] = None,
          add_role_ids: Optional[list[str]] = None, remove_role_ids: Optional[list[str]] = None, create_accounts: bool = False,
          interviewer: Optional[dict] = None) -> list[dict]:
    from app.employees import accounts, directory
    from app.employees import interviewers as iv

    cat = {c["id"]: c for c in catalog(db, tenant)}
    scope_of = {name: scope for name, _k, scope in CATALOG}
    unknown = [r for r in (set_role_ids or []) + (add_role_ids or []) + (remove_role_ids or []) if r not in cat]
    if unknown:
        raise RoleAdminError("Some of those roles can't be given from here.")
    results = []
    for e in employees:
        name = directory.name_of(e)
        user = db.get(User, e.user_id) if e.user_id else None
        invited = None
        if user is None:
            if not create_accounts:
                results.append({"employee_id": str(e.id), "name": name, "result": "no_account"})
                continue
            invited = accounts.send_invite(db, tenant, e, actor=actor.email)
            db.refresh(e)
            user = db.get(User, e.user_id) if e.user_id else None
            if user is None:
                results.append({"employee_id": str(e.id), "name": name, "result": "no_account"})
                continue
        held = {str(rid): r for rid, r in _assigned(db, tenant, user.id).items()}
        current = {rid for rid in held if rid in cat}
        if set_role_ids is not None:
            wanted = set(set_role_ids)
        else:
            wanted = (current | set(add_role_ids or [])) - set(remove_role_ids or [])
        add, remove = wanted - current, current - wanted
        removing_admin = {cat[r]["name"] for r in remove} & set(ADMIN_ROLES)
        if removing_admin and not ({held[r].name for r in held if r not in remove} & set(ADMIN_ROLES)) \
                and _admins_left(db, tenant, without_user=user.id) == 0:
            results.append({"employee_id": str(e.id), "name": name, "result": "last_admin",
                            "error": "This is the last HR Admin. Give HR Admin to someone else first."})
            continue
        added_names, removed_names = [], []
        try:
            for rid in sorted(add):
                role_name = cat[rid]["name"]
                if role_name == "Interviewer" and interviewer is not None:
                    iv.make_interviewer(db, tenant, e, pool_ids=interviewer.get("pool_ids") or [], skills=interviewer.get("skills") or [],
                                        max_per_day=interviewer.get("max_per_day"), actor=actor.email)
                else:
                    db.add(RoleAssignment(tenant_id=tenant.tenant_id, user_id=user.id, role_id=rid, scope_type=scope_of.get(role_name, "all")))
                added_names.append(role_name)
            for rid in sorted(remove):
                role_name = cat[rid]["name"]
                if role_name == "Interviewer":
                    iv.remove_interviewer(db, tenant, e, actor=actor.email)
                db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user.id,
                                                RoleAssignment.role_id == rid).delete(synchronize_session=False)
                removed_names.append(role_name)
            db.flush()
        except iv.InterviewerError as exc:
            db.rollback()
            results.append({"employee_id": str(e.id), "name": name, "result": "error", "error": str(exc)})
            continue
        final = {r.name for r in _assigned(db, tenant, user.id).values()}
        old_legacy = user.role
        user.role = _legacy_role(final, user.role)
        db.commit()
        changed = bool(added_names or removed_names)
        if changed:
            log_action(db, "employee", e.id, "roles_changed", actor.email[:50],
                       {"user": user.email, "added": added_names, "removed": removed_names, "legacy_role": [old_legacy, user.role]})
        emailed = _notify(db, tenant, user, name, sorted(final), added_names, removed_names) if changed else False
        results.append({"employee_id": str(e.id), "name": name, "result": "changed" if changed else "unchanged",
                        "added": added_names, "removed": removed_names, "invited": bool(invited), "emailed": emailed})
    return results


def _notify(db: Session, tenant, user: User, name: str, roles: list[str], added: list[str], removed: list[str]) -> bool:
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url
    from app.platform.settings.resolver import SettingContext, SettingsService

    if not SettingsService(db).get("employees.roles.notify_on_change", SettingContext(tenant=tenant)):
        return False
    label = {"HRBP": "HR"}
    try:
        send_default(db, tenant, "access.updated", to=[user.email], purpose="email.outbound.hr_letters",
                     ctx={"name": name, "roles": ", ".join(label.get(r, r) for r in roles) or "-",
                          "added": ", ".join(label.get(r, r) for r in added) or "-", "removed": ", ".join(label.get(r, r) for r in removed) or "-",
                          "link": public_app_url(db)},
                     related_entity_type="user", related_entity_id=user.id)
        return True
    except Exception:  # noqa: BLE001 -- the change is saved; the email is a courtesy
        return False
