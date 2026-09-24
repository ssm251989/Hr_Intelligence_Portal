"""platform/iam/roles.py (system role templates + the flat-role bridge) and
platform/iam/delegation.py (Part 5A CHECKS)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.models.iam import Role, RoleAssignment
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.iam.delegation import InvalidDelegationWindowError, active_delegations_for, create_delegation, revoke_delegation
from app.platform.iam.roles import _SYSTEM_ROLE_TEMPLATES, sync_role_assignments_for_existing_users, sync_system_roles
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_sync_system_roles_creates_every_template_role(db_session):
    roles_by_name = sync_system_roles(db_session, TENANT)
    assert set(roles_by_name) == set(_SYSTEM_ROLE_TEMPLATES)
    for role in roles_by_name.values():
        assert role.is_system is True


def test_sync_system_roles_is_idempotent_and_does_not_duplicate(db_session):
    sync_system_roles(db_session, TENANT)
    sync_system_roles(db_session, TENANT)
    count = db_session.query(Role).filter(Role.tenant_id == TENANT_1_ID, Role.name == "Super Admin", Role.is_system.is_(True)).count()
    assert count == 1


def test_super_admin_template_includes_every_registered_permission(db_session):
    roles_by_name = sync_system_roles(db_session, TENANT)
    from app.platform.iam.permissions import all_permissions

    assert set(roles_by_name["Super Admin"].permissions) == {p.code for p in all_permissions()}


def test_candidate_template_has_no_permissions(db_session):
    roles_by_name = sync_system_roles(db_session, TENANT)
    assert roles_by_name["Candidate"].permissions == []


def _make_user(db_session, role) -> User:
    user = User(email=f"bridge-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_bridge_assigns_matching_system_role_for_each_flat_role(db_session):
    admin = _make_user(db_session, "admin")
    recruiter = _make_user(db_session, "recruiter")

    created = sync_role_assignments_for_existing_users(db_session, TENANT)
    assert created >= 2

    assert has_permission(db_session, TENANT, admin, "iam.roles.configure") is True
    assert has_permission(db_session, TENANT, recruiter, "recruitment.job.view") is True
    assert has_permission(db_session, TENANT, recruiter, "iam.roles.configure") is False


def test_bridge_is_idempotent_and_does_not_duplicate_assignments(db_session):
    user = _make_user(db_session, "hiring_manager")
    sync_role_assignments_for_existing_users(db_session, TENANT)
    sync_role_assignments_for_existing_users(db_session, TENANT)

    count = db_session.query(RoleAssignment).filter(RoleAssignment.tenant_id == TENANT_1_ID, RoleAssignment.user_id == user.id).count()
    assert count == 1


def test_bridge_grants_hiring_manager_and_interviewer_their_own_scoped_permissions(db_session):
    hiring_manager = _make_user(db_session, "hiring_manager")
    interviewer = _make_user(db_session, "interviewer")
    sync_role_assignments_for_existing_users(db_session, TENANT)

    assert has_permission(db_session, TENANT, hiring_manager, "recruitment.offer.approve") is True
    assert has_permission(db_session, TENANT, interviewer, "recruitment.job.view") is True
    assert has_permission(db_session, TENANT, interviewer, "recruitment.offer.approve") is False


# ---- delegation.py ----


def test_create_delegation_rejects_ends_before_starts(db_session):
    a = _make_user(db_session, "recruiter")
    b = _make_user(db_session, "hiring_manager")
    now = datetime.now(timezone.utc)
    with pytest.raises(InvalidDelegationWindowError):
        create_delegation(db_session, TENANT, from_user_id=a.id, to_user_id=b.id, starts_at=now, ends_at=now - timedelta(hours=1))


def test_create_delegation_rejects_self_delegation(db_session):
    a = _make_user(db_session, "recruiter")
    now = datetime.now(timezone.utc)
    with pytest.raises(InvalidDelegationWindowError):
        create_delegation(db_session, TENANT, from_user_id=a.id, to_user_id=a.id, starts_at=now, ends_at=now + timedelta(hours=1))


def test_active_delegations_for_lists_only_currently_active_ones(db_session):
    a = _make_user(db_session, "recruiter")
    b = _make_user(db_session, "hiring_manager")
    now = datetime.now(timezone.utc)
    create_delegation(db_session, TENANT, from_user_id=a.id, to_user_id=b.id, starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))
    create_delegation(db_session, TENANT, from_user_id=a.id, to_user_id=b.id, starts_at=now - timedelta(days=5), ends_at=now - timedelta(days=1))

    active = active_delegations_for(db_session, TENANT, b.id, as_delegate=True)
    assert len(active) == 1


def test_revoke_delegation_removes_it(db_session):
    a = _make_user(db_session, "recruiter")
    b = _make_user(db_session, "hiring_manager")
    now = datetime.now(timezone.utc)
    delegation = create_delegation(db_session, TENANT, from_user_id=a.id, to_user_id=b.id, starts_at=now, ends_at=now + timedelta(hours=1))

    revoke_delegation(db_session, TENANT, delegation.id)

    assert active_delegations_for(db_session, TENANT, b.id, as_delegate=True) == []
