"""System role templates (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 2's own seeded
list) + the bridge that makes `authz.require()` resolve real permissions for this
installation's already-existing users immediately, without any separate UI setup step.

`sync_system_roles(db, tenant)` is idempotent and upserts by `(tenant_id, name)` -- safe to
call from app startup the same way `register_settings_definitions()`/`register_all()`
(comms purposes, IAM permissions) already are elsewhere.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.iam import Role, RoleAssignment
from app.models.user import User
from app.platform.iam.permissions import all_permissions, register_all as register_permissions
from app.platform.tenancy.context import TenantContext

# name -> a selector over platform.iam.permissions.all_permissions(): either "*" (every
# registered permission) or a list of (module, {actions}) filters, each widened to every
# resource under that module. Kept as filters rather than a hand-typed flat list so a
# newly `register_permission()`'d code is picked up by every role that already claims that
# module/action pair, without editing this file again.
_SYSTEM_ROLE_TEMPLATES: dict[str, str | list[tuple[str, set[str]]]] = {
    "Super Admin": "*",
    "HR Admin": [
        ("recruitment", {"view", "create", "edit", "delete", "approve", "export", "view_sensitive", "configure"}),
        ("core_hr", {"view", "create", "edit", "delete", "view_sensitive"}),
        ("platform", {"view", "configure"}),
        ("iam", {"view", "configure"}),
        ("workflow", {"view", "configure", "approve", "edit"}),
        ("onboarding", {"view", "create", "edit", "approve", "configure"}),
        ("performance", {"view", "create", "edit", "approve", "configure", "view_sensitive"}),
        ("compensation", {"view", "create", "edit", "approve", "configure", "export", "view_sensitive"}),
        ("helpdesk", {"view", "create", "edit", "view_sensitive", "export", "configure"}),
        ("assets", {"view", "create", "edit", "approve", "export"}),
        ("separation", {"view", "create", "edit", "approve", "export"}),
        ("analytics", {"view", "create", "edit", "export", "configure"}),
        ("copilot", {"view", "configure"}),
        ("agents", {"view", "create"}),
        ("ai", {"view", "configure"}),
        ("privacy", {"view", "create", "edit", "approve", "configure"}),
        ("security", {"export"}),
    ],
    "HRBP": [
        ("recruitment", {"view", "create", "edit", "export"}),
        ("core_hr", {"view", "create", "edit"}),
        ("iam", {"view"}),
        ("workflow", {"view", "approve"}),
        ("onboarding", {"view", "create", "edit"}),
        ("performance", {"view", "create", "edit"}),
        ("compensation", {"view"}),
        ("helpdesk", {"view", "create", "edit"}),
        ("assets", {"view", "create", "edit"}),
        ("copilot.chat", {"view"}),
        ("agents.suggestion", {"view"}),
        ("separation", {"view", "create", "edit"}),
        ("analytics", {"view", "create", "edit", "export"}),
        ("copilot", {"view"}),
        ("agents", {"view", "create"}),
    ],
    "Recruiter": [
        ("recruitment", {"view", "create", "edit"}),
        ("analytics.report", {"view", "create", "export"}),
        ("analytics.metrics", {"view"}),
        ("copilot.chat", {"view"}),
        ("agents", {"view", "create"}),
        ("workflow", {"view"}),
    ],
    "Hiring Manager": [
        ("recruitment", {"view", "approve"}),
        ("workflow", {"view", "approve"}),
    ],
    "Interviewer": [
        ("recruitment", {"view"}),
    ],
    "Helpdesk Agent": [
        ("recruitment", {"view"}),
        ("helpdesk", {"view", "create", "edit"}),
        ("assets", {"view", "create", "edit"}),
        ("workflow", {"view", "approve"}),
    ],
    "Manager": [
        ("recruitment", {"view", "approve"}),
        ("core_hr", {"view"}),
        ("onboarding", {"view", "edit"}),
        ("performance", {"view", "create", "edit"}),
        ("compensation", {"view", "create", "edit"}),
        ("separation", {"view", "approve"}),
        ("assets.asset", {"view"}),
        ("assets.self", {"view", "create"}),
        ("helpdesk.self", {"view", "create"}),
        ("analytics.report", {"view", "create", "export"}),
        ("analytics.metrics", {"view"}),
        ("analytics.dashboard", {"view"}),
        ("copilot.chat", {"view"}),
        ("workflow", {"view", "approve"}),
    ],
    "Employee": [
        ("workflow", {"view"}),
        ("performance.self", {"view", "edit"}),  # own goals/reviews/feedback only (the /me endpoints)
        ("helpdesk.self", {"view", "create"}),
        ("assets.self", {"view", "create"}),
        ("separation.self", {"view", "create"}),
        ("copilot.chat", {"view"}),
    ],
    "Candidate": [],
    "Auditor": [
        ("recruitment", {"view", "view_sensitive", "export"}),
        ("onboarding", {"view"}),
        ("performance", {"view"}),
        ("compensation", {"view"}),
        ("helpdesk", {"view", "export"}),
        ("assets", {"view", "export"}),
        ("separation", {"view", "export"}),
        ("analytics", {"view", "export"}),
        ("ai", {"view"}),
        ("privacy", {"view"}),
        ("security", {"export"}),
        ("core_hr", {"view", "view_sensitive"}),
        ("platform", {"view"}),
        ("iam", {"view"}),
        ("workflow", {"view"}),
    ],
}

# Bridges the 4 existing flat `users.role` string values (app/auth/dependencies.py's
# `require_roles`, unchanged by this part) onto a seeded system Role of the same
# effective scope, so a RoleAssignment exists for every real, already-logged-in user.
_FLAT_ROLE_BRIDGE = {
    "admin": "Super Admin",
    "recruiter": "Recruiter",
    "hiring_manager": "Hiring Manager",
    "interviewer": "Interviewer",
    # Part 9: a converted new hire's own login (onboarding/conversion.py) -- never
    # self-registrable, never admin-creatable via AdminUserCreate's Literal.
    "employee": "Employee",
}


def _permissions_for(selector) -> list[str]:
    if selector == "*":
        return [p.code for p in all_permissions()]
    codes = []
    for module, actions in selector:
        # "module" widens to every resource; "module.resource" narrows to one resource.
        module, _, resource = module.partition(".")
        codes.extend(
            p.code for p in all_permissions()
            if p.module == module and p.action in actions and (not resource or p.resource == resource)
        )
    return sorted(set(codes))


def sync_system_roles(db: Session, tenant: TenantContext) -> dict[str, Role]:
    """Upserts every _SYSTEM_ROLE_TEMPLATES row for this tenant, refreshing its
    `permissions` array to match the current registry (so a newly-registered permission
    reaches every role whose template selector covers it, on the next call) without
    touching a tenant's own hand-edited role name/description if they've cloned one."""
    register_permissions()
    roles_by_name: dict[str, Role] = {}
    for name, selector in _SYSTEM_ROLE_TEMPLATES.items():
        role = db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name == name, Role.is_system.is_(True)).first()
        permissions = _permissions_for(selector)
        if role is None:
            role = Role(tenant_id=tenant.tenant_id, name=name, is_system=True, permissions=permissions, description=f"System role template: {name}")
            db.add(role)
        else:
            role.permissions = permissions
        roles_by_name[name] = role
    db.commit()
    for role in roles_by_name.values():
        db.refresh(role)
    return roles_by_name


def bridge_single_user(db: Session, tenant: TenantContext, user: User, roles_by_name: Optional[dict[str, Role]] = None) -> Optional[RoleAssignment]:
    """Ensures ONE user has a scope_type="all" RoleAssignment matching their flat `role`
    column, if it's one of _FLAT_ROLE_BRIDGE's 4 -- called at the two real user-creation
    points (auth/router.py's register(), users/router.py's admin create_user()) so a brand
    new user is immediately covered by the new authz system, not just users who existed
    before Part 5. Returns None (a no-op) for a role that isn't bridgeable, or one that's
    already bridged."""
    role_name = _FLAT_ROLE_BRIDGE.get(user.role)
    if role_name is None:
        return None
    role = (roles_by_name or sync_system_roles(db, tenant))[role_name]
    existing = (
        db.query(RoleAssignment)
        .filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user.id, RoleAssignment.role_id == role.id)
        .first()
    )
    if existing is not None:
        return None
    assignment = RoleAssignment(tenant_id=tenant.tenant_id, user_id=user.id, role_id=role.id, scope_type="all")
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def sync_role_assignments_for_existing_users(db: Session, tenant: TenantContext) -> int:
    """Bulk form of bridge_single_user -- every User this tenant already has (a one-time
    backfill for users created before Part 5; hrctl or an admin action would call this,
    not a normal request path). Returns the count of assignments actually created."""
    roles_by_name = sync_system_roles(db, tenant)
    created = 0
    for user in db.query(User).filter(User.tenant_id == tenant.tenant_id).all():
        if bridge_single_user(db, tenant, user, roles_by_name) is not None:
            created += 1
    return created


def role_names_for(db: Session, tenant: TenantContext, user: User) -> list[str]:
    """Names of the caller's currently-active roles (report sharing, dashboard audiences,
    knowledge-document audiences all key on role NAME, which tenants recognise)."""
    from app.platform.iam.authz import active_role_assignments

    names = []
    for assignment in active_role_assignments(db, tenant, user.id):
        role = db.get(Role, assignment.role_id)
        if role is not None:
            names.append(role.name)
    return names
