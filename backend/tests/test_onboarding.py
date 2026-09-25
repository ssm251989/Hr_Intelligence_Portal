"""Pre-boarding & onboarding (docs/HRMS_COMPLETE_SPEC.txt Part 9). Covers this part's own
named TESTS: portal auth, plan generation relative dates, assignment rules, BGV webhook,
conversion idempotency -- plus API-level coverage of the HR + public routers.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.core_hr import Employee, EmploymentRecord
from app.models.iam import Role, RoleAssignment
from app.models.onboarding import OnboardingTask
from app.models.user import User
from app.onboarding import assignment_rules, bgv, conversion, dashboard, plans
from app.onboarding.portal import PortalAuthError, PortalValidationError, PreboardingPortal
from app.platform.metadata import forms as forms_service
from app.platform.metadata import masters
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")
TODAY = datetime.now(timezone.utc).date()

TASKS = [
    {"key": "laptop", "title": "Allocate laptop", "owner_role": "it", "due_offset_days": -7, "kind": "provisioning"},
    {"key": "email", "title": "Create email account", "owner_role": "it", "due_offset_days": -3, "depends_on": ["laptop"], "kind": "provisioning"},
    {"key": "welcome", "title": "Day-1 welcome", "owner_role": "manager", "due_offset_days": 0},
    {"key": "checkin_30", "title": "30-day check-in", "owner_role": "new_hire", "due_offset_days": 30, "kind": "checkin"},
]


def _portal(db_session) -> PreboardingPortal:
    return PreboardingPortal(db_session, TENANT)


def _case(db_session, *, joining_date=None, attributes=None, email=None):
    return _portal(db_session).create_case(
        email=email or f"joiner-{datetime.now().timestamp()}@example.com", first_name="Ravi", last_name="Kumar",
        joining_date=joining_date or TODAY + timedelta(days=14), attributes=attributes or {},
    )


# ---- portal auth ----


def test_create_case_creates_pre_hire_employee_and_token(db_session):
    case = _case(db_session)
    employee = db_session.get(Employee, case.employee_id)
    assert employee.status == "pre_hire"
    assert case.portal_token and case.portal_token_expires_at > datetime.now(timezone.utc)


def test_portal_auth_accepts_valid_token(db_session):
    case = _case(db_session)
    assert _portal(db_session).authenticate(case.portal_token).id == case.id


def test_portal_auth_rejects_unknown_token(db_session):
    with pytest.raises(PortalAuthError, match="invalid"):
        _portal(db_session).authenticate("not-a-real-token")


def test_portal_auth_rejects_expired_token(db_session):
    case = _case(db_session)
    case.portal_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    with pytest.raises(PortalAuthError, match="expired"):
        _portal(db_session).authenticate(case.portal_token)


def test_portal_auth_rejects_revoked_case(db_session):
    portal = _portal(db_session)
    case = _case(db_session)
    portal.revoke_offer(case, actor="hr", reason="budget freeze")
    with pytest.raises(PortalAuthError, match="closed"):
        portal.authenticate(case.portal_token)
    assert db_session.get(Employee, case.employee_id).status == "inactive"  # kept, not deleted


def test_rotate_token_invalidates_old_token(db_session):
    portal = _portal(db_session)
    case = _case(db_session)
    old = case.portal_token
    portal.rotate_token(case)
    with pytest.raises(PortalAuthError):
        portal.authenticate(old)


def test_public_portal_endpoint_401_on_bad_token(anonymous_client):
    response = anonymous_client.get("/api/v1/public/onboarding/portal/bogus")
    assert response.status_code == 401


def test_public_portal_endpoint_returns_view(anonymous_client, db_session):
    case = _case(db_session)
    response = anonymous_client.get(f"/api/v1/public/onboarding/portal/{case.portal_token}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invited"
    assert "history" not in body  # HR-only fields never reach the new hire


# ---- forms / documents / policies / readiness ----


def test_submit_form_enforces_required_fields(db_session):
    forms_service.upsert_form(db_session, TENANT, key="pb_personal", name="Personal", schema={"required": ["father_name"], "properties": {"father_name": {"type": "string"}}})
    portal = _portal(db_session)
    case = _case(db_session, attributes={"required_forms": ["pb_personal"]})
    with pytest.raises(PortalValidationError):
        portal.submit_form(case, "pb_personal", {})
    case = portal.submit_form(case, "pb_personal", {"father_name": "K"})
    assert "pb_personal" in case.form_submissions_json
    assert case.status == "ready"  # the only requirement is now met


def test_upload_requires_active_document_type(db_session):
    portal = _portal(db_session)
    case = _case(db_session)
    with pytest.raises(PortalValidationError):
        portal.upload_document(case, "no_such_type", b"x", "pdf")


def test_document_verification_drives_readiness(db_session):
    masters.create_value(db_session, TENANT, type_code="document_type", code="pb_pan", label_i18n={"en": "PAN"})
    portal = _portal(db_session)
    case = _case(db_session, attributes={"required_documents": ["pb_pan"]})
    doc = portal.upload_document(case, "pb_pan", b"%PDF", "pdf")
    assert portal.readiness(case)["percent"] == 0
    portal.verify_document(doc, actor="hr", approve=True)
    assert portal.readiness(case)["percent"] == 100


def test_extract_document_degrades_gracefully_without_ai_connection(db_session, monkeypatch):
    masters.create_value(db_session, TENANT, type_code="document_type", code="pb_degree", label_i18n={"en": "Degree"})
    portal = _portal(db_session)
    case = _case(db_session)
    doc = portal.upload_document(case, "pb_degree", b"x", "pdf")

    def _boom(*args, **kwargs):
        raise RuntimeError("no route")

    monkeypatch.setattr("app.platform.ai.governance.governed_json", _boom)
    doc = portal.extract_document(doc, "B.Tech 2020")
    assert doc.extracted_json == {"error": "RuntimeError"}
    assert doc.verification_status == "pending"  # AI never auto-verifies


def test_policy_ack_rejects_unknown_policy(db_session):
    portal = _portal(db_session)
    case = _case(db_session, attributes={"required_policies": ["code_of_conduct"]})
    with pytest.raises(PortalValidationError):
        portal.acknowledge_policy(case, "not_a_policy")
    case = portal.acknowledge_policy(case, "code_of_conduct")
    assert "code_of_conduct" in case.policy_acks_json


# ---- plan generation relative dates ----


def test_plan_generation_uses_relative_due_dates(db_session):
    doj = date(2026, 11, 2)
    template = plans.upsert_template(db_session, TENANT, code="std", name="Standard", tasks=TASKS)
    case = _case(db_session, joining_date=doj)
    plan = plans.generate_plan(db_session, TENANT, case, template)
    due = {t.key: t.due_date for t in plans.plan_tasks(db_session, TENANT, plan.id)}
    assert due == {"laptop": doj - timedelta(days=7), "email": doj - timedelta(days=3), "welcome": doj, "checkin_30": doj + timedelta(days=30)}


def test_plan_generation_is_idempotent(db_session):
    template = plans.upsert_template(db_session, TENANT, code="std", name="Standard", tasks=TASKS)
    case = _case(db_session)
    first = plans.generate_plan(db_session, TENANT, case, template)
    second = plans.generate_plan(db_session, TENANT, case, template)
    assert first.id == second.id
    assert db_session.query(OnboardingTask).filter(OnboardingTask.plan_id == first.id).count() == len(TASKS)


def test_dependencies_block_until_prerequisite_done(db_session):
    template = plans.upsert_template(db_session, TENANT, code="std", name="Standard", tasks=TASKS)
    plan = plans.generate_plan(db_session, TENANT, _case(db_session), template)
    tasks = {t.key: t for t in plans.plan_tasks(db_session, TENANT, plan.id)}
    assert tasks["email"].status == "blocked"
    with pytest.raises(plans.TaskBlockedError):
        plans.complete_task(db_session, TENANT, tasks["email"], actor="it")
    plans.complete_task(db_session, TENANT, tasks["laptop"], actor="it")
    db_session.refresh(tasks["email"])
    assert tasks["email"].status == "pending"


def test_joining_date_change_reschedules_open_tasks(db_session):
    doj = date(2026, 11, 2)
    template = plans.upsert_template(db_session, TENANT, code="std", name="Standard", tasks=TASKS)
    case = _case(db_session, joining_date=doj)
    plan = plans.generate_plan(db_session, TENANT, case, template)
    laptop = next(t for t in plans.plan_tasks(db_session, TENANT, plan.id) if t.key == "laptop")
    plans.complete_task(db_session, TENANT, laptop, actor="it")

    _portal(db_session).change_joining_date(case, doj + timedelta(days=7), actor="hr")
    due = {t.key: t.due_date for t in plans.plan_tasks(db_session, TENANT, plan.id)}
    assert due["welcome"] == doj + timedelta(days=7)
    assert due["laptop"] == doj - timedelta(days=7)  # done tasks keep their original date
    assert case.history_json[-1]["event"] == "joining_date_changed"


@pytest.mark.parametrize("bad", [
    [{"key": "a", "title": "A", "owner_role": "wizard"}],
    [{"key": "a", "title": "A", "owner_role": "hr", "depends_on": ["missing"]}],
    [{"key": "a", "title": "A", "owner_role": "hr", "depends_on": ["b"]}, {"key": "b", "title": "B", "owner_role": "hr", "depends_on": ["a"]}],
    [{"key": "a", "title": "A", "owner_role": "hr"}, {"key": "a", "title": "dup", "owner_role": "hr"}],
])
def test_invalid_plan_templates_rejected(db_session, bad):
    with pytest.raises(plans.InvalidPlanTemplateError):
        plans.upsert_template(db_session, TENANT, code="bad", name="Bad", tasks=bad)


# ---- assignment rules ----


def test_assignment_rules_lowest_priority_wins(db_session):
    assignment_rules.create_rule(db_session, TENANT, name="fallback", target_type="onboarding_plan_template", target_ref="std", priority=500)
    assignment_rules.create_rule(
        db_session, TENANT, name="interns", target_type="onboarding_plan_template", target_ref="intern",
        condition_jsonlogic={"==": [{"var": "worker_type"}, "intern"]}, priority=10,
    )
    assert assignment_rules.resolve_one(db_session, TENANT, "onboarding_plan_template", {"worker_type": "intern"}) == "intern"
    assert assignment_rules.resolve_one(db_session, TENANT, "onboarding_plan_template", {"worker_type": "employee"}) == "std"


def test_assignment_rules_roles_are_additive(db_session):
    assignment_rules.create_rule(db_session, TENANT, name="all", target_type="role", target_ref="Employee")
    assignment_rules.create_rule(db_session, TENANT, name="mgr", target_type="role", target_ref="Manager", condition_jsonlogic={"in": [{"var": "grade"}, ["M1", "M2"]]})
    assert assignment_rules.resolve_all(db_session, TENANT, "role", {"grade": "M1"}) == ["Employee", "Manager"]
    assert assignment_rules.resolve_all(db_session, TENANT, "role", {"grade": "G1"}) == ["Employee"]


def test_assignment_rule_rejects_unknown_target_type(db_session):
    with pytest.raises(assignment_rules.InvalidAssignmentRuleError):
        assignment_rules.create_rule(db_session, TENANT, name="x", target_type="nope", target_ref="y")


# ---- BGV ----


def _bgv_case(db_session, checks=("identity", "education")):
    case = _case(db_session)
    return bgv.create_case(db_session, TENANT, subject_type="candidate", subject_id=case.employee_id, package=list(checks), preboarding_case_id=case.id)


def test_bgv_initiation_requires_consent(db_session):
    case = _bgv_case(db_session)
    with pytest.raises(bgv.BgvConsentRequiredError):
        bgv.initiate(db_session, case)
    bgv.record_consent(db_session, case, consent_text="I authorise verification")
    assert bgv.initiate(db_session, case).status == "initiated"


def test_bgv_webhook_updates_checks_and_completes(anonymous_client, db_session):
    case = _bgv_case(db_session)
    bgv.record_consent(db_session, case, consent_text="ok")
    bgv.initiate(db_session, case)

    headers = {"X-Bgv-Token": case.webhook_token}
    r1 = anonymous_client.post("/api/v1/public/onboarding/bgv/webhook", headers=headers, json={"checks": [{"type": "identity", "status": "clear"}]})
    assert r1.status_code == 200 and r1.json()["status"] == "in_progress"
    r2 = anonymous_client.post("/api/v1/public/onboarding/bgv/webhook", headers=headers, json={"checks": [{"type": "education", "status": "discrepancy", "notes": "year mismatch"}], "discrepancy": "year mismatch"})
    assert r2.json()["status"] == "completed"
    db_session.refresh(case)
    assert case.decision == "pending"  # vendor never decides -- HITL


def test_bgv_webhook_rejects_bad_token(anonymous_client):
    response = anonymous_client.post("/api/v1/public/onboarding/bgv/webhook", headers={"X-Bgv-Token": "nope"}, json={"checks": []})
    assert response.status_code == 401


def test_bgv_webhook_rejects_check_outside_package(db_session):
    case = _bgv_case(db_session, checks=("identity",))
    bgv.record_consent(db_session, case, consent_text="ok")
    bgv.initiate(db_session, case)
    with pytest.raises(bgv.BgvError):
        bgv.apply_webhook(db_session, case, {"checks": [{"type": "criminal", "status": "clear"}]})


def test_bgv_clear_decision_requires_all_checks_clear(db_session):
    case = _bgv_case(db_session)
    bgv.record_consent(db_session, case, consent_text="ok")
    bgv.initiate(db_session, case)
    bgv.apply_webhook(db_session, case, {"checks": [{"type": "identity", "status": "clear"}, {"type": "education", "status": "discrepancy"}]})
    with pytest.raises(bgv.BgvError):
        bgv.decide(db_session, case, decision="clear", actor="hr")
    assert bgv.decide(db_session, case, decision="accept_with_discrepancy", actor="hr").decided_by == "hr"


# ---- conversion ----


def test_conversion_refused_before_doj(db_session):
    case = _case(db_session, joining_date=TODAY + timedelta(days=3))
    with pytest.raises(conversion.ConversionError):
        conversion.convert(db_session, TENANT, case, actor="hr")


def test_conversion_creates_active_employee_user_and_hire_record(db_session):
    plans.upsert_template(db_session, TENANT, code="std", name="Standard", tasks=TASKS)
    assignment_rules.create_rule(db_session, TENANT, name="default plan", target_type="onboarding_plan_template", target_ref="std")
    case = _case(db_session, joining_date=TODAY, attributes={"designation": "SDE1", "grade": "G1"})

    result = conversion.convert(db_session, TENANT, case, actor="hr")

    employee = db_session.get(Employee, case.employee_id)
    assert employee.status == "active" and employee.employee_code == result["employee_code"]
    user = db_session.get(User, employee.user_id)
    assert user.role == "employee" and user.email == case.email
    employee_role = db_session.query(Role).filter(Role.tenant_id == TENANT.tenant_id, Role.name == "Employee").one()
    assert db_session.query(RoleAssignment).filter(RoleAssignment.user_id == user.id, RoleAssignment.role_id == employee_role.id).count() == 1
    record = db_session.query(EmploymentRecord).filter(EmploymentRecord.employee_id == employee.id).one()
    assert record.designation == "SDE1" and record.effective_from == TODAY
    assert result["plan_id"] is not None
    assert case.status == "joined"


def test_conversion_is_idempotent(db_session):
    case = _case(db_session, joining_date=TODAY)
    first = conversion.convert(db_session, TENANT, case, actor="hr")
    second = conversion.convert(db_session, TENANT, case, actor="hr")
    assert second["already_converted"] is True
    assert (first["employee_id"], first["user_id"]) == (second["employee_id"], second["user_id"])
    assert db_session.query(EmploymentRecord).filter(EmploymentRecord.employee_id == case.employee_id).count() == 1
    assert db_session.query(User).filter(User.email == case.email).count() == 1


def test_conversion_refused_for_revoked_case(db_session):
    portal = _portal(db_session)
    case = _case(db_session, joining_date=TODAY)
    portal.revoke_offer(case, actor="hr")
    with pytest.raises(conversion.ConversionError):
        conversion.convert(db_session, TENANT, case, actor="hr")


def test_conversion_blocked_by_bgv_when_setting_on(db_session, monkeypatch):
    from app.platform.settings.resolver import SettingsService

    original = SettingsService.get
    monkeypatch.setattr(SettingsService, "get", lambda self, key, ctx: True if key == "onboarding.bgv.block_conversion_until_clear" else original(self, key, ctx))
    case = _case(db_session, joining_date=TODAY)
    bgv.create_case(db_session, TENANT, subject_type="candidate", subject_id=case.employee_id, package=["identity"], preboarding_case_id=case.id)
    with pytest.raises(conversion.ConversionError, match="background verification"):
        conversion.convert(db_session, TENANT, case, actor="hr")


# ---- dashboard + API ----


def test_dashboard_reports_upcoming_and_dropoff(db_session):
    portal = _portal(db_session)
    _case(db_session, joining_date=TODAY + timedelta(days=5))
    revoked = _case(db_session, joining_date=TODAY + timedelta(days=5))
    portal.revoke_offer(revoked, actor="hr")
    summary = dashboard.summary(db_session, TENANT, today=TODAY)
    assert any(j["joining_date"] == (TODAY + timedelta(days=5)).isoformat() for j in summary["upcoming_joiners"])
    assert summary["cases_by_status"]["revoked"] >= 1
    assert summary["offer_to_join_drop_off_percent"] > 0


def test_api_create_case_and_convert(client):
    created = client.post("/api/v1/onboarding/cases", json={"email": "api-joiner@example.com", "first_name": "Api", "joining_date": TODAY.isoformat()})
    assert created.status_code == 201
    assert "portal_token" in created.json()
    case_id = created.json()["id"]
    assert client.post(f"/api/v1/onboarding/cases/{case_id}/convert", json={"confirm_joined": False}).status_code == 400
    converted = client.post(f"/api/v1/onboarding/cases/{case_id}/convert", json={"confirm_joined": True})
    assert converted.status_code == 200
    assert "portal_token" not in client.get(f"/api/v1/onboarding/cases/{case_id}").json()


def test_api_requires_permission(make_auth_headers, anonymous_client):
    headers = make_auth_headers(role="interviewer")
    assert anonymous_client.get("/api/v1/onboarding/cases", headers=headers).status_code == 403


def test_api_assignment_preview(client):
    client.post("/api/v1/onboarding/assignment-rules", json={"name": "r", "target_type": "role", "target_ref": "Employee"})
    preview = client.post("/api/v1/onboarding/assignment-rules/preview", json={"context": {}})
    assert preview.status_code == 200 and "Employee" in preview.json()["roles"]
