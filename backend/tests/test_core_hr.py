"""Core HR (docs/HRMS_COMPLETE_SPEC.txt Part 7): org model, employee master, lifecycle,
documents, letters, import wizard. `client` is bridged to "Super Admin" (every permission)
via conftest.py's own bridge_single_user call -- same pattern as test_iam_api.py.

Covers this part's own named TESTS: effective-dating queries (as-of date), lifecycle
workflows, position vacancy logic, masking of PII, import dry-run/rollback, org chart
cycles prevention -- plus API-level coverage of every router endpoint.
"""

from datetime import date, timedelta

import pytest

from app.core_hr import documents as documents_service
from app.core_hr import employees as employees_service
from app.core_hr import import_wizard
from app.core_hr import letters as letters_service
from app.core_hr import lifecycle
from app.core_hr import org as org_service
from app.models.core_hr import Department, Employee, LegalEntity, Position
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _make_employee(db_session, **kwargs) -> Employee:
    return employees_service.create_employee(db_session, TENANT, first_name=kwargs.pop("first_name", "Asha"), **kwargs)


# ---- employee master + employee_code sequence ----


def test_create_employee_auto_generates_employee_code(db_session):
    employee = _make_employee(db_session, last_name="Rao")
    assert employee.employee_code.startswith("EMP-")
    assert employee.status == "pre_hire"


def test_encrypted_field_round_trips_and_is_never_stored_plaintext(db_session):
    employee = _make_employee(db_session)
    employees_service.set_encrypted_field(db_session, TENANT, employee, "pan", "ABCDE1234F", created_by="tester")

    db_session.refresh(employee)
    assert employee.pan_secret_ref is not None
    assert "ABCDE1234F" not in (employee.pan_secret_ref or "")

    revealed = employees_service.get_encrypted_field(db_session, TENANT, employee, "pan")
    assert revealed == "ABCDE1234F"


def test_masking_of_pii_aadhaar_shows_only_last_4(db_session):
    employee = _make_employee(db_session)
    employees_service.set_encrypted_field(db_session, TENANT, employee, "aadhaar", "123456789012", created_by="tester")
    db_session.refresh(employee)

    assert employees_service.masked_aadhaar(employee) == "XXXX-XXXX-9012"
    as_dict = employees_service.employee_to_dict(employee)
    assert as_dict["aadhaar"] == "XXXX-XXXX-9012"
    assert as_dict["pan"] is None  # never set for this employee -- no ref, no reveal


def test_set_encrypted_field_rejects_unknown_field(db_session):
    employee = _make_employee(db_session)
    with pytest.raises(ValueError):
        employees_service.set_encrypted_field(db_session, TENANT, employee, "not_a_real_field", "x", created_by="tester")


# ---- lifecycle / effective-dating ----


def test_apply_event_carries_forward_unspecified_fields(db_session):
    employee = _make_employee(db_session)
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="hire", effective_from=date(2026, 1, 1), changes={"designation": "SDE1", "grade": "G1"})
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="promotion", effective_from=date(2026, 6, 1), changes={"grade": "G2"})

    current = lifecycle.get_current_employment(db_session, TENANT, employee.id)
    assert current.grade == "G2"
    assert current.designation == "SDE1"  # carried forward from the hire record, not re-specified


def test_effective_dating_as_of_date_query(db_session):
    employee = _make_employee(db_session)
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="hire", effective_from=date(2026, 1, 1), changes={"designation": "SDE1"})
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="promotion", effective_from=date(2026, 6, 1), changes={"designation": "SDE2"})

    before = lifecycle.get_current_employment(db_session, TENANT, employee.id, as_of=date(2026, 3, 1))
    after = lifecycle.get_current_employment(db_session, TENANT, employee.id, as_of=date(2026, 7, 1))
    assert before.designation == "SDE1"
    assert after.designation == "SDE2"

    history = lifecycle.employment_history(db_session, TENANT, employee.id)
    assert [r.designation for r in history] == ["SDE2", "SDE1"]


def test_apply_event_rejects_unknown_event_type(db_session):
    employee = _make_employee(db_session)
    with pytest.raises(lifecycle.InvalidLifecycleEventError):
        lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="not_a_real_event", effective_from=date.today(), changes={})


def test_request_event_applies_immediately_when_no_workflow_is_published(db_session):
    employee = _make_employee(db_session)
    result = lifecycle.request_event(db_session, TENANT, employee_id=employee.id, event_type="hire", effective_from=date.today(), changes={"designation": "SDE1"}, created_by="tester")
    assert result["applied"] is True
    assert result["record"].designation == "SDE1"


def test_request_event_gates_behind_a_published_workflow_when_one_exists(db_session):
    import uuid

    from app.core.security import hash_password
    from app.models.user import User
    from app.platform.workflow import definitions

    approver = User(email=f"core-hr-approver-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="Approver", role="recruiter")
    db_session.add(approver)
    db_session.commit()
    db_session.refresh(approver)

    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    draft = definitions.create_draft(db_session, TENANT.tenant_id, key="core_hr.lifecycle.transfer", name="Transfer approval", trigger={}, graph=graph)
    definitions.publish(db_session, draft, actor="test")

    employee = _make_employee(db_session)
    result = lifecycle.request_event(db_session, TENANT, employee_id=employee.id, event_type="transfer", effective_from=date.today(), changes={}, created_by="tester")
    assert result["applied"] is False
    assert result["workflow_instance_id"] is not None

    # nothing was written to employment_records yet -- still gated
    assert lifecycle.get_current_employment(db_session, TENANT, employee.id) is None


# ---- org model: departments, positions, vacancy, org chart cycles ----


def test_position_vacancy_logic(db_session):
    department = Department(tenant_id=TENANT.tenant_id, name="Engineering")
    db_session.add(department)
    db_session.commit()
    db_session.refresh(department)

    position = Position(tenant_id=TENANT.tenant_id, code="ENG-001", title="Engineer", department_id=department.id, status="vacant")
    db_session.add(position)
    db_session.commit()
    db_session.refresh(position)

    assert position.status == "vacant"
    position.status = "filled"
    db_session.commit()
    db_session.refresh(position)
    assert position.status == "filled"


def test_org_chart_cycle_prevention(db_session):
    a = Position(tenant_id=TENANT.tenant_id, code="A", title="A")
    b = Position(tenant_id=TENANT.tenant_id, code="B", title="B")
    db_session.add_all([a, b])
    db_session.commit()
    db_session.refresh(a)
    db_session.refresh(b)

    org_service.set_reports_to(db_session, TENANT, b.id, a.id)  # b reports to a -- fine
    with pytest.raises(org_service.OrgChartCycleError):
        org_service.set_reports_to(db_session, TENANT, a.id, b.id)  # would create a<->b cycle


def test_org_chart_by_position_is_a_lazy_one_level_tree(db_session):
    root = Position(tenant_id=TENANT.tenant_id, code="ROOT", title="Root")
    db_session.add(root)
    db_session.commit()
    db_session.refresh(root)
    child = Position(tenant_id=TENANT.tenant_id, code="CHILD", title="Child", reports_to_position_id=root.id)
    db_session.add(child)
    db_session.commit()

    top_level = org_service.org_chart_by_position(db_session, TENANT, None)
    assert any(row["id"] == str(root.id) and row["has_children"] is True for row in top_level)

    under_root = org_service.org_chart_by_position(db_session, TENANT, root.id)
    assert [row["id"] for row in under_root] == [str(child.id)]


# ---- documents ----


def test_check_expiring_documents_finds_only_the_near_term_window(db_session):
    employee = _make_employee(db_session)
    documents_service.add_document(db_session, TENANT, employee_id=employee.id, doc_type="passport", expiry_date=date.today() + timedelta(days=10))
    documents_service.add_document(db_session, TENANT, employee_id=employee.id, doc_type="visa", expiry_date=date.today() + timedelta(days=400))

    expiring = documents_service.check_expiring_documents(db_session, TENANT, within_days=30)
    assert {d.type for d in expiring} == {"passport"}


# ---- letters ----


def test_letter_generate_and_verify_round_trip(db_session):
    template = letters_service.create_draft(db_session, TENANT, key="offer", name="Offer Letter", html_tpl="<p>Hello {{ first_name }}</p>", variables_schema={"required": ["first_name"]})
    letters_service.publish(db_session, template)

    employee = _make_employee(db_session)
    record = letters_service.generate_letter(db_session, TENANT, employee_id=employee.id, template_key="offer", context={"first_name": "Asha"}, generated_by="tester")
    assert "Asha" in record.rendered_html

    verified = letters_service.verify_letter(db_session, TENANT, record.verification_token)
    assert verified.id == record.id


def test_generate_letter_requires_a_published_template(db_session):
    employee = _make_employee(db_session)
    with pytest.raises(letters_service.LetterTemplateNotFoundError):
        letters_service.generate_letter(db_session, TENANT, employee_id=employee.id, template_key="noc", context={}, generated_by="tester")


# ---- import wizard: dry-run / commit / rollback ----


def test_import_batch_validates_rows_on_creation(db_session):
    batch = import_wizard.create_batch(
        db_session, TENANT, entity="employee",
        rows=[{"name": "Valid Person"}, {"name": ""}],
        column_mapping={"name": "first_name"}, created_by="tester",
    )
    assert batch.row_count == 2
    assert batch.error_count == 1


def test_import_dry_run_then_commit_then_rollback(db_session):
    batch = import_wizard.create_batch(
        db_session, TENANT, entity="employee",
        rows=[{"name": "Import Person"}],
        column_mapping={"name": "first_name"}, created_by="tester",
    )
    import_wizard.mark_dry_run(db_session, TENANT, batch.id)

    result = import_wizard.commit_batch(db_session, TENANT, batch.id, created_by="tester")
    assert result["committed"] == 1
    created = db_session.query(Employee).filter(Employee.tenant_id == TENANT.tenant_id, Employee.first_name == "Import Person").first()
    assert created is not None

    deleted = import_wizard.rollback_batch(db_session, TENANT, batch.id)
    assert deleted == 1
    assert db_session.query(Employee).filter(Employee.tenant_id == TENANT.tenant_id, Employee.first_name == "Import Person").first() is None


def test_rollback_only_touches_rows_this_batch_committed(db_session):
    untouched = _make_employee(db_session, first_name="Pre Existing")
    batch = import_wizard.create_batch(db_session, TENANT, entity="employee", rows=[{"name": "Batch Person"}], column_mapping={"name": "first_name"}, created_by="tester")
    import_wizard.commit_batch(db_session, TENANT, batch.id, created_by="tester")
    import_wizard.rollback_batch(db_session, TENANT, batch.id)

    still_there = db_session.get(Employee, untouched.id)
    assert still_there is not None


def test_commit_batch_requires_preview_or_dry_run_state(db_session):
    batch = import_wizard.create_batch(db_session, TENANT, entity="employee", rows=[], column_mapping={}, created_by="tester")
    import_wizard.mark_dry_run(db_session, TENANT, batch.id)
    import_wizard.commit_batch(db_session, TENANT, batch.id, created_by="tester")
    with pytest.raises(import_wizard.ImportBatchStateError):
        import_wizard.commit_batch(db_session, TENANT, batch.id, created_by="tester")


def test_create_batch_rejects_unsupported_entity(db_session):
    with pytest.raises(ValueError):
        import_wizard.create_batch(db_session, TENANT, entity="not_a_real_entity", rows=[], column_mapping={}, created_by="tester")


# ---- API router ----


def test_api_create_and_get_employee(client):
    created = client.post("/api/v1/core-hr/employees", json={"first_name": "Ravi", "last_name": "Kumar"})
    assert created.status_code == 201
    body = created.json()
    assert body["employee_code"].startswith("EMP-")

    fetched = client.get(f"/api/v1/core-hr/employees/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["first_name"] == "Ravi"


def test_api_encrypted_field_set_and_reveal_is_audited(client, db_session):
    from app.models.audit_log import AuditLog

    employee_id = client.post("/api/v1/core-hr/employees", json={"first_name": "Priya"}).json()["id"]

    set_response = client.put(f"/api/v1/core-hr/employees/{employee_id}/encrypted-field", json={"field": "bank_account", "value": "1234567890"})
    assert set_response.status_code == 200

    reveal_response = client.get(f"/api/v1/core-hr/employees/{employee_id}/encrypted-field/bank_account")
    assert reveal_response.status_code == 200
    assert reveal_response.json()["value"] == "1234567890"

    audit_row = db_session.query(AuditLog).filter(AuditLog.entity_id == employee_id, AuditLog.action == "sensitive_field_revealed").first()
    assert audit_row is not None


def test_api_legal_entity_and_department_and_position_crud(client):
    legal_entity = client.post("/api/v1/core-hr/legal-entities", json={"name": "Acme India Pvt Ltd"})
    assert legal_entity.status_code == 201

    department = client.post("/api/v1/core-hr/departments", json={"name": "Platform Engineering"})
    assert department.status_code == 201

    position = client.post("/api/v1/core-hr/positions", json={"code": "PLT-001", "title": "Staff Engineer", "department_id": department.json()["id"]})
    assert position.status_code == 201
    assert position.json()["status"] == "vacant"

    listed = client.get("/api/v1/core-hr/positions")
    assert any(p["code"] == "PLT-001" for p in listed.json())


def test_api_reports_to_rejects_a_cycle(client):
    a = client.post("/api/v1/core-hr/positions", json={"code": "CYC-A", "title": "A"}).json()
    b = client.post("/api/v1/core-hr/positions", json={"code": "CYC-B", "title": "B"}).json()

    ok = client.patch(f"/api/v1/core-hr/positions/{b['id']}/reports-to", json={"reports_to_position_id": a["id"]})
    assert ok.status_code == 200

    cycle = client.patch(f"/api/v1/core-hr/positions/{a['id']}/reports-to", json={"reports_to_position_id": b["id"]})
    assert cycle.status_code == 400


def test_api_lifecycle_event_and_employment_history(client):
    employee_id = client.post("/api/v1/core-hr/employees", json={"first_name": "Neha"}).json()["id"]

    requested = client.post(
        f"/api/v1/core-hr/employees/{employee_id}/lifecycle-events",
        json={"event_type": "hire", "effective_from": str(date.today()), "changes": {"designation": "Analyst"}},
    )
    assert requested.status_code == 200
    assert requested.json()["applied"] is True

    history = client.get(f"/api/v1/core-hr/employees/{employee_id}/employment-history")
    assert history.status_code == 200
    assert history.json()[0]["designation"] == "Analyst"

    current = client.get(f"/api/v1/core-hr/employees/{employee_id}/employment-current")
    assert current.status_code == 200
    assert current.json()["designation"] == "Analyst"


def test_api_documents_add_and_list(client):
    employee_id = client.post("/api/v1/core-hr/employees", json={"first_name": "Kiran"}).json()["id"]
    added = client.post(f"/api/v1/core-hr/employees/{employee_id}/documents", json={"doc_type": "pan_card", "visibility": "hr"})
    assert added.status_code == 201

    listed = client.get(f"/api/v1/core-hr/employees/{employee_id}/documents")
    assert len(listed.json()) == 1


def test_api_letter_template_publish_and_generate_and_public_verify(client):
    created = client.post("/api/v1/core-hr/letter-templates", json={"key": "confirmation", "name": "Confirmation Letter", "html_tpl": "<p>Hi {{ first_name }}</p>", "variables_schema": {"required": ["first_name"]}})
    assert created.status_code == 201
    template_id = created.json()["id"]

    published = client.post(f"/api/v1/core-hr/letter-templates/{template_id}/publish")
    assert published.status_code == 200

    employee_id = client.post("/api/v1/core-hr/employees", json={"first_name": "Divya"}).json()["id"]
    generated = client.post(f"/api/v1/core-hr/employees/{employee_id}/letters", json={"template_key": "confirmation", "context": {"first_name": "Divya"}})
    assert generated.status_code == 201
    token = generated.json()["verification_token"]

    verify_page = client.get(f"/api/v1/public/core-hr/letters/verify/{token}")
    assert verify_page.status_code == 200
    assert "verified" in verify_page.text.lower()


def test_api_letter_publish_rejects_a_template_with_unresolvable_variables(client):
    created = client.post("/api/v1/core-hr/letter-templates", json={"key": "noc", "name": "NOC", "html_tpl": "{% garbage %}"})
    template_id = created.json()["id"]
    published = client.post(f"/api/v1/core-hr/letter-templates/{template_id}/publish")
    assert published.status_code == 400


def test_api_import_wizard_full_cycle(client):
    created = client.post(
        "/api/v1/core-hr/import-batches",
        json={"entity": "employee", "rows": [{"n": "Imported One"}], "column_mapping": {"n": "first_name"}},
    )
    assert created.status_code == 201
    batch_id = created.json()["id"]

    rows = client.get(f"/api/v1/core-hr/import-batches/{batch_id}/rows")
    assert rows.json()[0]["status"] == "valid"

    dry_run = client.post(f"/api/v1/core-hr/import-batches/{batch_id}/dry-run")
    assert dry_run.status_code == 200

    committed = client.post(f"/api/v1/core-hr/import-batches/{batch_id}/commit")
    assert committed.status_code == 200
    assert committed.json()["committed"] == 1

    rolled_back = client.post(f"/api/v1/core-hr/import-batches/{batch_id}/rollback")
    assert rolled_back.status_code == 200
    assert rolled_back.json()["deleted"] == 1
