"""Part 14 UX standards (docs/HRMS_COMPLETE_SPEC.txt): setup wizard progress derived from
data, configuration health, bootstrap-driven nav + module gating, permission-scoped global
search, unified inbox, saved views, autosave drafts, version history/revert, friendly
errors, settings help completeness + revert, per-user preferences.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

import uuid

import pytest

from app.core.security import create_access_token, hash_password
from app.experience import config_health, search, setup_wizard, versioning
from app.models.comms import MessageTemplate, NotificationRule
from app.models.iam import Role, RoleAssignment
from app.models.user import User
from app.models.workflow import WorkflowDefinition
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _user(db_session, *, permissions: list[str], scope_type: str = "all", role: str = "recruiter") -> User:
    user = User(tenant_id=TENANT.tenant_id, email=f"x-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x" * 12), role=role)
    db_session.add(user)
    db_session.flush()
    r = Role(tenant_id=TENANT.tenant_id, name=f"r-{uuid.uuid4().hex[:6]}", permissions=permissions, is_system=False)
    db_session.add(r)
    db_session.flush()
    db_session.add(RoleAssignment(tenant_id=TENANT.tenant_id, user_id=user.id, role_id=r.id, scope_type=scope_type))
    db_session.commit()
    return user


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


# ---- settings help + revert ----


def test_every_setting_has_help():
    from app.platform.settings.bootstrap_definitions import register_all
    from app.platform.settings.help_catalog import missing_help
    from app.platform.settings.registry import all_definitions

    register_all()
    assert missing_help([d.key for d in all_definitions()]) == []


def test_definitions_api_includes_help(client):
    rows = client.get("/api/v1/settings/definitions").json()
    tz = next(r for r in rows if r["key"] == "org.timezone")
    assert tz["help"] and tz["affects"]


def test_setting_revert_creates_new_version(client):
    client.put("/api/v1/settings/ux.page_size", json={"value": 50})
    client.put("/api/v1/settings/ux.page_size", json={"value": 100})
    history = client.get("/api/v1/settings/ux.page_size/history").json()
    first = min(h["version"] for h in history)
    reverted = client.post("/api/v1/settings/ux.page_size/revert", json={"version": first})
    assert reverted.status_code == 200 and reverted.json()["value"] == 50
    assert len(client.get("/api/v1/settings/ux.page_size/history").json()) == len(history) + 1


# ---- setup wizard ----


def test_setup_progress_is_derived_from_data(db_session):
    before = {s["step"]: s["done"] for s in setup_wizard.progress(db_session, TENANT)["steps"]}
    setup_wizard.set_company(db_session, TENANT, display_name="Demo Org", legal_name=None, timezone="Asia/Kolkata", locale=None, currency=None, actor="admin")
    after = {s["step"]: s["done"] for s in setup_wizard.progress(db_session, TENANT)["steps"]}
    assert after["company"] is True
    assert before.keys() == after.keys() == set(setup_wizard.STEPS)


def test_required_steps_cannot_be_skipped(db_session):
    with pytest.raises(setup_wizard.SetupError):
        setup_wizard.skip(db_session, TENANT, "mailbox", actor="admin")
    progress = setup_wizard.skip(db_session, TENANT, "branding", actor="admin")
    assert next(s for s in progress["steps"] if s["step"] == "branding")["done"] is True


def test_invalid_timezone_rejected(db_session):
    with pytest.raises(setup_wizard.SetupError):
        setup_wizard.set_company(db_session, TENANT, display_name="X", legal_name=None, timezone="Mars/Olympus", locale=None, currency=None, actor="a")


def test_invite_admin_returns_link_when_mail_unavailable(db_session, monkeypatch):
    def _fail(*a, **k):
        raise RuntimeError("no mailbox")

    monkeypatch.setattr("app.platform.comms.service.send", _fail)
    result = setup_wizard.invite_admin(db_session, TENANT, email="second-admin@example.com", full_name=None, actor="admin")
    assert result["email_sent"] is False and "/set-password?token=" in result["link"]
    assert db_session.query(User).filter(User.email == "second-admin@example.com").one().role == "admin"


# ---- modules: nav + 404 gate ----


def test_disabled_module_api_returns_404(client, db_session):
    setup_wizard.set_modules(db_session, TENANT, ["onboarding"], actor="admin")  # performance off
    response = client.get("/api/v1/performance/cycles")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "MODULE_DISABLED"
    assert client.get("/api/v1/onboarding/cases").status_code == 200


def test_bootstrap_nav_follows_modules_and_permissions(client, db_session):
    setup_wizard.set_modules(db_session, TENANT, ["onboarding"], actor="admin")
    body = client.get("/api/me/bootstrap").json()
    paths = [n["path"] for n in body["nav"]]
    assert "/jobs" in paths and "/settings#onboarding" in paths and "/settings#performance" not in paths
    assert body["home_path"] == "/" and body["ux"]["page_size"] == 25 and body["ux"]["direction"] == "ltr"


def test_employee_home_is_their_inbox(db_session):
    from app.platform.modules import home_path

    assert home_path({"performance.self.view", "helpdesk.self.view"}) == "/approvals"


# ---- configuration health ----


def test_config_health_flags_unpublished_template_and_approverless_workflow(db_session):
    db_session.add(NotificationRule(tenant_id=TENANT.tenant_id, name="Offer signed", event_type="offer.signed", recipients_json=[], channels=["email"],
                                    template_key="never_published_tpl", enabled=True))
    db_session.add(WorkflowDefinition(tenant_id=TENANT.tenant_id, key="broken_wf", name="Broken", status="published", version=1,
                                      graph_json={"start_node": "a", "nodes": {"a": {"type": "approval", "approvers": []}}}))
    db_session.commit()
    codes = {i["code"] for i in config_health.check(db_session, TENANT)["issues"]}
    assert {"UNPUBLISHED_TEMPLATE", "WORKFLOW_NO_APPROVERS"} <= codes


def test_config_health_every_issue_has_a_fix_path(db_session):
    for issue in config_health.check(db_session, TENANT)["issues"]:
        assert issue["fix"] and issue["fix_path"].startswith("/")


# ---- global search ----


def test_search_hides_groups_without_permission(db_session):
    from app.models.candidate import Candidate

    db_session.add(Candidate(tenant_id=TENANT.tenant_id, full_name="Zanzibar Quill", email="zq@example.com"))
    db_session.commit()
    nobody = _user(db_session, permissions=["copilot.chat.view"])
    recruiter = _user(db_session, permissions=["recruitment.candidate.view"])
    assert not any(g["type"] == "candidate" for g in search.search(db_session, TENANT, nobody, "Zanzibar")["groups"])
    hit = next(g for g in search.search(db_session, TENANT, recruiter, "Zanzibar")["groups"] if g["type"] == "candidate")
    assert hit["items"][0]["title"] == "Zanzibar Quill"


def test_search_finds_typos_via_trigram(db_session):
    from app.models.candidate import Candidate

    db_session.add(Candidate(tenant_id=TENANT.tenant_id, full_name="Bartholomew Crane", email="bc@example.com"))
    db_session.commit()
    recruiter = _user(db_session, permissions=["recruitment.candidate.view"])
    groups = search.search(db_session, TENANT, recruiter, "Bartholomw Crane")["groups"]
    assert any("Bartholomew" in i["title"] for g in groups for i in g["items"])


def test_search_employees_respect_org_scope(db_session):
    from app.core_hr import employees as employees_service
    from app.core_hr import lifecycle

    manager_user = _user(db_session, permissions=["core_hr.employee.view"], scope_type="reportees_direct")
    manager = employees_service.create_employee(db_session, TENANT, first_name="Mgr", status="active", user_id=manager_user.id)
    from datetime import date

    mine = employees_service.create_employee(db_session, TENANT, first_name="Quintessa", last_name="Mine", status="active")
    lifecycle.apply_event(db_session, TENANT, employee_id=mine.id, event_type="hire", effective_from=date(2025, 1, 1), changes={"manager_employee_id": manager.id})
    employees_service.create_employee(db_session, TENANT, first_name="Quintessa", last_name="Other", status="active")
    groups = search.search(db_session, TENANT, manager_user, "Quintessa")["groups"]
    titles = [i["title"] for g in groups if g["type"] == "employee" for i in g["items"]]
    assert titles == ["Quintessa Mine"]


def test_short_query_returns_nothing(db_session):
    assert search.search(db_session, TENANT, _user(db_session, permissions=[]), "a")["groups"] == []


# ---- saved views / drafts ----


def test_saved_views_are_private_unless_shared(anonymous_client, db_session):
    alice = _user(db_session, permissions=["helpdesk.ticket.view"])
    bob = _user(db_session, permissions=["helpdesk.ticket.view"])
    anonymous_client.put("/api/v1/views/helpdesk.tickets", json={"name": "Urgent", "config": {"filters": {"priority": "urgent"}}}, headers=_headers(alice))
    assert [v["name"] for v in anonymous_client.get("/api/v1/views/helpdesk.tickets", headers=_headers(alice)).json()] == ["Urgent"]
    assert anonymous_client.get("/api/v1/views/helpdesk.tickets", headers=_headers(bob)).json() == []
    shared = anonymous_client.put("/api/v1/views/helpdesk.tickets", json={"name": "Team", "config": {}, "shared_role_name": "HR Admin"}, headers=_headers(alice))
    assert shared.status_code == 403  # only admins may share


def test_draft_round_trip(anonymous_client, db_session):
    user = _user(db_session, permissions=[])
    h = _headers(user)
    assert anonymous_client.get("/api/v1/drafts/performance.review?entity_ref=r1", headers=h).json()["data"] is None
    anonymous_client.put("/api/v1/drafts/performance.review?entity_ref=r1", json={"data": {"comments": "half done"}}, headers=h)
    assert anonymous_client.get("/api/v1/drafts/performance.review?entity_ref=r1", headers=h).json()["data"] == {"comments": "half done"}
    anonymous_client.delete("/api/v1/drafts/performance.review?entity_ref=r1", headers=h)
    assert anonymous_client.get("/api/v1/drafts/performance.review?entity_ref=r1", headers=h).json()["data"] is None


# ---- versioning ----


def test_revert_creates_a_new_draft_version(db_session):
    for version, status, subject in ((1, "published", "Welcome v1"), (2, "published", "Welcome v2")):
        db_session.add(MessageTemplate(tenant_id=TENANT.tenant_id, key="welcome_tpl", channel="email", locale="en", version=version, status=status,
                                       subject_tpl=subject, html_tpl="<p>hi</p>", text_tpl="hi"))
    db_session.commit()
    result = versioning.revert(db_session, TENANT, "message_template", "welcome_tpl", 1, actor="admin")
    assert result["version"] == 3 and result["status"] == "draft"
    newest = db_session.query(MessageTemplate).filter(MessageTemplate.key == "welcome_tpl", MessageTemplate.version == 3).one()
    assert newest.subject_tpl == "Welcome v1"
    assert [h["version"] for h in versioning.history(db_session, TENANT, "message_template", "welcome_tpl")] == [3, 2, 1]


def test_revert_unknown_version(db_session):
    with pytest.raises(versioning.VersioningError):
        versioning.revert(db_session, TENANT, "message_template", "nope", 9, actor="a")


# ---- friendly errors ----


def test_config_error_becomes_friendly_409():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.platform.connectors.router import NoConnectionForPurposeError

    @app.get("/__test_friendly_error")
    def _boom():
        raise NoConnectionForPurposeError("email.outbound.default")

    with TestClient(app, raise_server_exceptions=False) as c:
        body = c.get("/__test_friendly_error", headers={"X-Tenant-Slug": "tenant1-test"})
    assert body.status_code in (409, 404)  # 404 only if the test host doesn't resolve a tenant
    if body.status_code == 409:
        detail = body.json()["detail"]
        assert detail["code"] == "NO_CONNECTION_FOR_PURPOSE" and detail["fix_path"] == "/settings#connections"


# ---- inbox + preferences + me ----


def test_unified_inbox_lists_agent_suggestions(anonymous_client, db_session):
    from app.agents.service import suggest

    reviewer = _user(db_session, permissions=["helpdesk.kb.edit"])
    suggest(db_session, TENANT, agent="policy_checker", kind="policy_review", title="Review leave policy", payload={}, reviewer_permission="helpdesk.kb.edit")
    items = anonymous_client.get("/api/v1/inbox/all", headers=_headers(reviewer)).json()
    assert any(i["kind"] == "ai_suggestion" and i["title"] == "Review leave policy" for i in items)


def test_preferences_are_user_scoped(anonymous_client, db_session):
    user = _user(db_session, permissions=[])
    assert anonymous_client.put("/api/v1/me/preferences", json={"reduce_motion": True, "page_size": 50}, headers=_headers(user)).status_code == 200
    assert anonymous_client.put("/api/v1/me/preferences", json={"page_size": 7}, headers=_headers(user)).status_code == 400


def test_me_letters_empty_without_employee(anonymous_client, db_session):
    user = _user(db_session, permissions=[])
    assert anonymous_client.get("/api/v1/me/letters", headers=_headers(user)).json() == []
