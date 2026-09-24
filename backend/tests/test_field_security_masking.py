"""platform/iam/field_security.py (Part 5A CHECKS)."""

import uuid

from app.core.security import hash_password
from app.models.iam import FieldSecurity, Role, RoleAssignment
from app.models.user import User
from app.platform.iam.field_security import apply_field_security, filter_write_fields
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session) -> User:
    user = User(email=f"fs-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _role_with_rule(db_session, user, entity, field, access) -> Role:
    role = Role(tenant_id=TENANT_1_ID, name=f"FS-{uuid.uuid4().hex[:6]}", permissions=[])
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    db_session.add(RoleAssignment(tenant_id=TENANT_1_ID, user_id=user.id, role_id=role.id, scope_type="all"))
    db_session.add(FieldSecurity(tenant_id=TENANT_1_ID, entity=entity, field=field, role_id=role.id, access=access))
    db_session.commit()
    return role


def test_unrestricted_field_passes_through_unchanged(db_session):
    user = _make_user(db_session)
    result = apply_field_security(db_session, TENANT, user, "employee", {"name": "Jane", "salary": 100000})
    assert result == {"name": "Jane", "salary": 100000}


def test_hidden_field_is_removed_entirely(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "salary", "hidden")
    result = apply_field_security(db_session, TENANT, user, "employee", {"name": "Jane", "salary": 100000})
    assert result == {"name": "Jane"}
    assert "salary" not in result


def test_masked_field_becomes_placeholder(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "pan_number", "masked")
    result = apply_field_security(db_session, TENANT, user, "employee", {"pan_number": "ABCDE1234F"})
    assert result["pan_number"] != "ABCDE1234F"
    assert result["pan_number"] == "••••"


def test_field_security_is_scoped_per_entity(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "salary", "hidden")
    result = apply_field_security(db_session, TENANT, user, "candidate", {"salary": 100000})
    assert result == {"salary": 100000}


def test_most_permissive_role_wins_across_multiple_roles(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "salary", "hidden")
    _role_with_rule(db_session, user, "employee", "salary", "write")
    result = apply_field_security(db_session, TENANT, user, "employee", {"salary": 100000})
    assert result == {"salary": 100000}


def test_filter_write_fields_strips_read_only_fields(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "salary", "read")
    filtered = filter_write_fields(db_session, TENANT, user, "employee", {"name": "Jane", "salary": 999999})
    assert filtered == {"name": "Jane"}


def test_filter_write_fields_strips_hidden_and_masked_too(db_session):
    user = _make_user(db_session)
    _role_with_rule(db_session, user, "employee", "salary", "hidden")
    _role_with_rule(db_session, user, "employee", "pan_number", "masked")
    filtered = filter_write_fields(db_session, TENANT, user, "employee", {"name": "Jane", "salary": 1, "pan_number": "X"})
    assert filtered == {"name": "Jane"}
