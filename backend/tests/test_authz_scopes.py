"""platform/iam/authz.py -- permission resolution, scope_filter, delegation, custom
condition_jsonlogic (Part 5A CHECKS)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.iam import Role, RoleAssignment, UserDelegation
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import ScopeNotSupportedError, effective_permissions, has_permission, permits_row, require, scope_filter
from app.platform.iam.permissions import register_all as register_permissions
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

register_permissions()

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session, role="recruiter", email=None) -> User:
    import uuid

    from app.core.security import hash_password

    user = User(email=email or f"authz-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_role(db_session, name, permissions, is_system=False) -> Role:
    role = Role(tenant_id=TENANT_1_ID, name=name, permissions=permissions, is_system=is_system)
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


def _assign(db_session, user, role, scope_type="all", scope_ids=None, condition=None, valid_from=None, valid_to=None):
    assignment = RoleAssignment(
        tenant_id=TENANT_1_ID, user_id=user.id, role_id=role.id, scope_type=scope_type,
        scope_ids=scope_ids or [], condition_jsonlogic=condition, valid_from=valid_from, valid_to=valid_to,
    )
    db_session.add(assignment)
    db_session.commit()
    return assignment


def test_user_with_no_role_assignments_has_no_permissions(db_session):
    user = _make_user(db_session)
    assert effective_permissions(db_session, TENANT, user) == set()
    assert has_permission(db_session, TENANT, user, "recruitment.job.view") is False


def test_role_assignment_grants_its_role_permissions(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "Test Viewer", ["recruitment.job.view"])
    _assign(db_session, user, role)
    assert has_permission(db_session, TENANT, user, "recruitment.job.view") is True
    assert has_permission(db_session, TENANT, user, "recruitment.job.delete") is False


def test_multiple_roles_union_their_permissions(db_session):
    user = _make_user(db_session)
    role_a = _make_role(db_session, "A", ["recruitment.job.view"])
    role_b = _make_role(db_session, "B", ["recruitment.job.delete"])
    _assign(db_session, user, role_a)
    _assign(db_session, user, role_b)
    assert has_permission(db_session, TENANT, user, "recruitment.job.view") is True
    assert has_permission(db_session, TENANT, user, "recruitment.job.delete") is True


def test_role_assignment_outside_its_valid_window_does_not_grant(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "Future", ["recruitment.job.view"])
    future = datetime.now(timezone.utc) + timedelta(days=5)
    _assign(db_session, user, role, valid_from=future)
    assert has_permission(db_session, TENANT, user, "recruitment.job.view") is False


def test_role_assignment_after_its_valid_to_does_not_grant(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "Expired", ["recruitment.job.view"])
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _assign(db_session, user, role, valid_to=past)
    assert has_permission(db_session, TENANT, user, "recruitment.job.view") is False


def test_active_delegation_grants_delegate_the_delegator_permissions(db_session):
    delegator = _make_user(db_session, email="delegator@example.com")
    delegate = _make_user(db_session, email="delegate@example.com")
    role = _make_role(db_session, "Owner", ["recruitment.offer.approve"])
    _assign(db_session, delegator, role)

    now = datetime.now(timezone.utc)
    db_session.add(UserDelegation(tenant_id=TENANT_1_ID, from_user_id=delegator.id, to_user_id=delegate.id, permissions=None, starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1)))
    db_session.commit()

    assert has_permission(db_session, TENANT, delegate, "recruitment.offer.approve") is True


def test_delegation_can_be_scoped_to_a_subset_of_permissions(db_session):
    delegator = _make_user(db_session, email="delegator2@example.com")
    delegate = _make_user(db_session, email="delegate2@example.com")
    role = _make_role(db_session, "Owner2", ["recruitment.offer.approve", "recruitment.offer.delete"])
    _assign(db_session, delegator, role)

    now = datetime.now(timezone.utc)
    db_session.add(UserDelegation(tenant_id=TENANT_1_ID, from_user_id=delegator.id, to_user_id=delegate.id, permissions=["recruitment.offer.approve"], starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1)))
    db_session.commit()

    assert has_permission(db_session, TENANT, delegate, "recruitment.offer.approve") is True
    assert has_permission(db_session, TENANT, delegate, "recruitment.offer.delete") is False


def test_expired_delegation_grants_nothing(db_session):
    delegator = _make_user(db_session, email="delegator3@example.com")
    delegate = _make_user(db_session, email="delegate3@example.com")
    role = _make_role(db_session, "Owner3", ["recruitment.offer.approve"])
    _assign(db_session, delegator, role)

    now = datetime.now(timezone.utc)
    db_session.add(UserDelegation(tenant_id=TENANT_1_ID, from_user_id=delegator.id, to_user_id=delegate.id, permissions=None, starts_at=now - timedelta(days=5), ends_at=now - timedelta(days=1)))
    db_session.commit()

    assert has_permission(db_session, TENANT, delegate, "recruitment.offer.approve") is False


def test_scope_filter_returns_unfiltered_query_for_all_scope(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "AllScope", ["recruitment.job.view"])
    _assign(db_session, user, role, scope_type="all")

    query = db_session.query(JobRole)
    filtered = scope_filter(query, model=JobRole, permission_code="recruitment.job.view", user=user, db=db_session, tenant=TENANT)
    assert filtered is query


def test_scope_filter_self_scope_filters_by_owner_column(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "SelfScope", ["recruitment.job.view"])
    _assign(db_session, user, role, scope_type="self")

    query = db_session.query(User)
    filtered = scope_filter(query, model=User, permission_code="recruitment.job.view", user=user, db=db_session, tenant=TENANT, owner_column=User.id)
    assert str(user.id) in str(filtered.whereclause) or filtered.whereclause is not None


def test_scope_filter_self_scope_without_owner_column_raises(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "SelfScopeNoCol", ["recruitment.job.view"])
    _assign(db_session, user, role, scope_type="self")

    with pytest.raises(ScopeNotSupportedError):
        scope_filter(db_session.query(JobRole), model=JobRole, permission_code="recruitment.job.view", user=user, db=db_session, tenant=TENANT)


@pytest.mark.parametrize("scope_type", ["legal_entity", "business_unit", "location", "department", "cost_center", "reportees_direct", "reportees_all"])
def test_scope_filter_org_hierarchy_scopes_raise_not_supported(db_session, scope_type):
    user = _make_user(db_session, email=f"org-{scope_type}@example.com")
    role = _make_role(db_session, f"Org-{scope_type}", ["recruitment.job.view"])
    _assign(db_session, user, role, scope_type=scope_type)

    with pytest.raises(ScopeNotSupportedError):
        scope_filter(db_session.query(JobRole), model=JobRole, permission_code="recruitment.job.view", user=user, db=db_session, tenant=TENANT)


def test_permits_row_evaluates_custom_condition_jsonlogic(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "CustomScope", ["recruitment.offer.approve"])
    _assign(db_session, user, role, scope_type="custom", condition={"<": [{"var": "amount"}, 100000]})

    assert permits_row(db_session, TENANT, user, "recruitment.offer.approve", {"amount": 50000}) is True
    assert permits_row(db_session, TENANT, user, "recruitment.offer.approve", {"amount": 500000}) is False


def test_require_dependency_raises_403_without_permission(db_session):
    from fastapi import HTTPException

    user = _make_user(db_session)
    dependency = require("recruitment.job.delete")
    with pytest.raises(HTTPException) as exc_info:
        dependency(current_user=user, db=db_session)
    assert exc_info.value.status_code == 403


def test_require_dependency_returns_user_with_permission(db_session):
    user = _make_user(db_session)
    role = _make_role(db_session, "CanDelete", ["recruitment.job.delete"])
    _assign(db_session, user, role)

    dependency = require("recruitment.job.delete")
    assert dependency(current_user=user, db=db_session) is user
