"""Part 20: add / remove an app role on an employee's account (Employee, Interviewer, ...), audited."""

from sqlalchemy.orm import Session

from app.models.iam import Role, RoleAssignment
from app.models.user import User


def add_roles(db: Session, tenant, user: User, names: list[str]) -> list[str]:
    from app.platform.iam.roles import sync_system_roles

    sync_system_roles(db, tenant)
    added = []
    for name in dict.fromkeys(n for n in names if n):
        role = db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name == name).first()
        if role is None:
            continue
        exists = db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user.id,
                                                 RoleAssignment.role_id == role.id).first()
        if exists is None:
            db.add(RoleAssignment(tenant_id=tenant.tenant_id, user_id=user.id, role_id=role.id, scope_type="self"))
            added.append(name)
    db.commit()
    return added


def remove_roles(db: Session, tenant, user: User, names: list[str]) -> list[str]:
    ids = [r.id for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name.in_(names)).all()]
    if not ids:
        return []
    n = db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.user_id == user.id,
                                        RoleAssignment.role_id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return names if n else []


def role_names(db: Session, tenant, user: User) -> list[str]:
    roles = {r.id: r.name for r in db.query(Role).filter(Role.tenant_id == tenant.tenant_id).all()}
    return sorted({roles.get(a.role_id, "") for a in db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id,
                                                                                      RoleAssignment.user_id == user.id).all()} - {""})
