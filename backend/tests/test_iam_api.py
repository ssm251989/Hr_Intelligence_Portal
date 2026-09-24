"""platform/iam/api_router.py -- roles/role-assignments/field-security/delegations CRUD,
admin MFA reset, access review, impersonation (Part 5A CHECKS). `client` is bridged to
"Super Admin" (every permission) via conftest.py's own bridge_single_user call."""

from app.models.user import User


def test_list_permissions_returns_the_registered_catalog(client):
    response = client.get("/api/v1/iam/permissions")
    assert response.status_code == 200
    codes = {p["code"] for p in response.json()}
    assert "recruitment.job.view" in codes


def test_list_roles_includes_every_system_role_template(client):
    response = client.get("/api/v1/iam/roles")
    assert response.status_code == 200
    names = {r["name"] for r in response.json()}
    assert {"Super Admin", "HR Admin", "Recruiter", "Candidate"} <= names


def test_create_update_delete_a_custom_role(client):
    created = client.post("/api/v1/iam/roles", json={"name": "Test Custom Role", "permissions": ["recruitment.job.view"]})
    assert created.status_code == 201
    role_id = created.json()["id"]
    assert created.json()["is_system"] is False

    updated = client.patch(f"/api/v1/iam/roles/{role_id}", json={"permissions": ["recruitment.job.view", "recruitment.job.edit"]})
    assert updated.status_code == 200
    assert set(updated.json()["permissions"]) == {"recruitment.job.view", "recruitment.job.edit"}

    deleted = client.delete(f"/api/v1/iam/roles/{role_id}")
    assert deleted.status_code == 204


def test_system_roles_cannot_be_deleted(client):
    roles = client.get("/api/v1/iam/roles").json()
    system_role = next(r for r in roles if r["is_system"])
    response = client.delete(f"/api/v1/iam/roles/{system_role['id']}")
    assert response.status_code == 400


def test_create_and_list_and_delete_a_role_assignment(client, db_session):
    target = User(email="assignee@example.com", hashed_password="x", full_name="Assignee", role="recruiter")
    db_session.add(target)
    db_session.commit()
    db_session.refresh(target)

    role_id = next(r["id"] for r in client.get("/api/v1/iam/roles").json() if r["name"] == "Recruiter")

    created = client.post("/api/v1/iam/role-assignments", json={"user_id": str(target.id), "role_id": role_id, "scope_type": "all"})
    assert created.status_code == 201
    assignment_id = created.json()["id"]

    listed = client.get("/api/v1/iam/role-assignments", params={"user_id": str(target.id)}).json()
    assert any(a["id"] == assignment_id for a in listed)

    deleted = client.delete(f"/api/v1/iam/role-assignments/{assignment_id}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/iam/role-assignments", params={"user_id": str(target.id)}).json() == []


def test_upsert_and_list_and_delete_field_security(client):
    role_id = next(r["id"] for r in client.get("/api/v1/iam/roles").json() if r["name"] == "Interviewer")

    upserted = client.put("/api/v1/iam/field-security", json={"entity": "employee", "field": "salary", "role_id": role_id, "access": "hidden"})
    assert upserted.status_code == 200
    rule_id = upserted.json()["id"]

    # upsert again with a different access level updates the same row, not a duplicate
    reupserted = client.put("/api/v1/iam/field-security", json={"entity": "employee", "field": "salary", "role_id": role_id, "access": "masked"})
    assert reupserted.json()["id"] == rule_id
    assert reupserted.json()["access"] == "masked"

    listed = client.get("/api/v1/iam/field-security", params={"entity": "employee"}).json()
    assert len(listed) == 1

    deleted = client.delete(f"/api/v1/iam/field-security/{rule_id}")
    assert deleted.status_code == 204


def test_create_and_list_and_revoke_a_delegation(client, db_session):
    from datetime import datetime, timedelta, timezone

    delegate = User(email="delegate-api@example.com", hashed_password="x", full_name="D", role="recruiter")
    db_session.add(delegate)
    db_session.commit()
    db_session.refresh(delegate)

    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/iam/delegations",
        json={"to_user_id": str(delegate.id), "starts_at": (now - timedelta(hours=1)).isoformat(), "ends_at": (now + timedelta(hours=1)).isoformat()},
    )
    assert created.status_code == 201
    delegation_id = created.json()["id"]

    listed = client.get("/api/v1/iam/delegations").json()
    assert any(d["id"] == delegation_id for d in listed)

    deleted = client.delete(f"/api/v1/iam/delegations/{delegation_id}")
    assert deleted.status_code == 204


def test_admin_mfa_reset_disables_enrollment(client, db_session):
    import pyotp

    from app.core.security import hash_password
    from app.platform.iam import mfa
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    target = User(email="mfa-reset-target@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(target)
    db_session.commit()
    db_session.refresh(target)

    secret, _uri = mfa.start_totp_enrollment(db_session, tenant, target)
    mfa.confirm_totp_enrollment(db_session, tenant, target, pyotp.totp.TOTP(secret).now())
    assert mfa.is_mfa_enrolled(target) is True

    response = client.post(f"/api/v1/iam/users/{target.id}/mfa/reset")
    assert response.status_code == 204

    db_session.refresh(target)
    assert mfa.is_mfa_enrolled(target) is False


def test_access_review_lists_users_holding_a_permission(client, db_session):
    target = User(email="reviewer-target@example.com", hashed_password="x", full_name="T", role="recruiter")
    db_session.add(target)
    db_session.commit()
    db_session.refresh(target)
    role_id = next(r["id"] for r in client.get("/api/v1/iam/roles").json() if r["name"] == "Recruiter")
    client.post("/api/v1/iam/role-assignments", json={"user_id": str(target.id), "role_id": role_id, "scope_type": "all"})

    response = client.get("/api/v1/iam/access-review", params={"permission": "recruitment.job.view"})
    assert response.status_code == 200
    emails = {row["email"] for row in response.json()}
    assert "reviewer-target@example.com" in emails


def test_impersonation_issues_a_usable_token_and_is_audited(client, db_session):
    from app.models.audit_log import AuditLog

    target = User(email="impersonate-target@example.com", hashed_password="x", full_name="T", role="recruiter")
    db_session.add(target)
    db_session.commit()
    db_session.refresh(target)

    response = client.post(f"/api/v1/iam/impersonate/{target.id}")
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "impersonate-target@example.com"

    audit_row = db_session.query(AuditLog).filter(AuditLog.entity_id == target.id, AuditLog.action == "impersonation_started").first()
    assert audit_row is not None
