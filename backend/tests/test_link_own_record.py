"""M1 (Part 27): an admin whose login has no employee record could not use My profile / Exits, and nothing said how to link it."""

import uuid

from app.core_hr import employees as employees_service
from app.models.core_hr import Employee
from app.models.user import User
from app.platform.tenancy.context import TENANT_1_ID, TenantContext


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _admin(db):
    u = User(email=f"m1-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Meena Iyer", role="admin")
    db.add(u)
    db.commit()
    return u


def test_admin_creates_their_own_employee_record(client, db_session, monkeypatch):
    monkeypatch.setattr("app.platform.iam.authz.has_permission", lambda db, tenant, user, code: True)
    u = _admin(db_session)
    from app.core.security import create_access_token

    h = {"Authorization": f"Bearer {create_access_token(str(u.id))}"}
    assert client.get("/api/v1/ui/self-service/me", headers=h).json()["linked"] is False
    r = client.post("/api/v1/ui/self-service/me/link", json={"mode": "create"}, headers=h)
    assert r.status_code == 200, r.text
    e = db_session.query(Employee).filter(Employee.user_id == u.id).one()
    assert (e.first_name, e.last_name, e.company_email) == ("Meena", "Iyer", u.email)
    again = client.post("/api/v1/ui/self-service/me/link", json={"mode": "create"}, headers=h)
    assert again.status_code == 400  # already linked


def test_admin_links_an_existing_record_by_employee_id(client, db_session, monkeypatch):
    monkeypatch.setattr("app.platform.iam.authz.has_permission", lambda db, tenant, user, code: True)
    u = _admin(db_session)
    e = employees_service.create_employee(db_session, _tenant(), first_name="Meena", status="active")
    from app.core.security import create_access_token

    h = {"Authorization": f"Bearer {create_access_token(str(u.id))}"}
    r = client.post("/api/v1/ui/self-service/me/link", json={"mode": "link", "employee_code": e.employee_code}, headers=h)
    assert r.status_code == 200, r.text
    db_session.refresh(e)
    assert e.user_id == u.id


def test_only_admins_can_link_themselves(client, db_session, monkeypatch):
    monkeypatch.setattr("app.platform.iam.authz.has_permission", lambda db, tenant, user, code: False)
    u = _admin(db_session)
    from app.core.security import create_access_token

    r = client.post("/api/v1/ui/self-service/me/link", json={"mode": "create"}, headers={"Authorization": f"Bearer {create_access_token(str(u.id))}"})
    assert r.status_code == 403
