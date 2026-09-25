"""Analytics, report builder, HR Copilot, agents, AI governance (docs/HRMS_COMPLETE_SPEC.txt
Part 12). Covers this part's named TESTS: dataset scoping (manager sees only reportees),
scheduled report delivery, RAG citations required, copilot tool authz, AI disabled ->
features hidden, budget cutoff -- plus redaction, decision log, HITL agents.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents import service as agents
from app.analytics import metrics, schedules
from app.analytics.report_builder import ReportBuilder, ReportError, ReportPermissionError, to_csv
from app.copilot import retrieval
from app.copilot.service import CopilotService
from app.core.security import hash_password
from app.core_hr import employees as employees_service
from app.core_hr import lifecycle
from app.models.iam import Role, RoleAssignment
from app.models.intelligence import AgentSuggestion, AiDecisionLog, AiUsageBudget, AiUsageRecord, CopilotDraft, SavedReport
from app.models.user import User
from app.platform.ai import governance
from app.platform.iam.org_scope import employee_ids_in_scope
from app.platform.settings.resolver import SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _user(db_session, *, permissions: list[str], scope_type: str = "all", role_name: str = None) -> User:
    user = User(tenant_id=TENANT.tenant_id, email=f"u-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x" * 12), role="recruiter")
    db_session.add(user)
    db_session.flush()
    role = Role(tenant_id=TENANT.tenant_id, name=role_name or f"test-role-{uuid.uuid4().hex[:6]}", permissions=permissions, is_system=False)
    db_session.add(role)
    db_session.flush()
    db_session.add(RoleAssignment(tenant_id=TENANT.tenant_id, user_id=user.id, role_id=role.id, scope_type=scope_type))
    db_session.commit()
    return user


def _employee(db_session, *, manager_id=None, user=None, grade="G1"):
    emp = employees_service.create_employee(db_session, TENANT, first_name="E", status="active", user_id=user.id if user else None)
    lifecycle.apply_event(db_session, TENANT, employee_id=emp.id, event_type="hire", effective_from=date(2025, 1, 1),
                          changes={"manager_employee_id": manager_id, "grade": grade})
    return emp


def _patch_setting(monkeypatch, overrides: dict):
    original = SettingsService.get
    monkeypatch.setattr(SettingsService, "get", lambda self, key, ctx: overrides[key] if key in overrides else original(self, key, ctx))


# ---- dataset scoping ----


def test_manager_sees_only_reportees(db_session):
    manager_user = _user(db_session, permissions=["core_hr.employee.view", "analytics.report.view"], scope_type="reportees_direct")
    manager = _employee(db_session, user=manager_user)
    report_a = _employee(db_session, manager_id=manager.id)
    report_b = _employee(db_session, manager_id=manager.id)
    outsider = _employee(db_session)

    assert employee_ids_in_scope(db_session, TENANT, manager_user, "core_hr.employee.view") == {report_a.id, report_b.id}
    result = ReportBuilder(db_session, TENANT, manager_user).run("headcount", {"columns": ["employee_id"], "limit": 1000})
    ids = {r["employee_id"] for r in result["rows"]}
    assert ids == {str(report_a.id), str(report_b.id)}
    assert str(outsider.id) not in ids and str(manager.id) not in ids


def test_all_scope_is_unrestricted_and_no_permission_is_refused(db_session):
    hr = _user(db_session, permissions=["core_hr.employee.view"])
    assert employee_ids_in_scope(db_session, TENANT, hr, "core_hr.employee.view") is None
    nobody = _user(db_session, permissions=["analytics.report.view"])
    with pytest.raises(ReportPermissionError):
        ReportBuilder(db_session, TENANT, nobody).run("headcount", {"columns": ["employee_id"]})


def test_reportees_all_is_transitive(db_session):
    top_user = _user(db_session, permissions=["core_hr.employee.view"], scope_type="reportees_all")
    top = _employee(db_session, user=top_user)
    mid = _employee(db_session, manager_id=top.id)
    leaf = _employee(db_session, manager_id=mid.id)
    assert employee_ids_in_scope(db_session, TENANT, top_user, "core_hr.employee.view") == {mid.id, leaf.id}


def test_grouping_and_measures(db_session):
    hr = _user(db_session, permissions=["core_hr.employee.view"])
    for grade in ("G1", "G1", "G2"):
        _employee(db_session, grade=grade)
    result = ReportBuilder(db_session, TENANT, hr).run("headcount", {
        "group_by": ["grade"], "measures": [{"field": "employee_id", "agg": "count", "as": "n"}],
        "filters": [{"field": "grade", "op": "in", "value": ["G1", "G2"]}], "sort": [{"field": "grade", "dir": "asc"}],
    })
    counts = {r["grade"]: r["n"] for r in result["rows"]}
    assert counts["G1"] >= 2 and counts["G2"] >= 1
    assert b"grade" in to_csv(result)


def test_unknown_field_and_operator_rejected(db_session):
    hr = _user(db_session, permissions=["core_hr.employee.view"])
    with pytest.raises(ReportError):
        ReportBuilder(db_session, TENANT, hr).run("headcount", {"columns": ["salary_secret"]})
    with pytest.raises(ReportError):
        ReportBuilder(db_session, TENANT, hr).run("headcount", {"filters": [{"field": "grade", "op": "drop_table", "value": 1}]})


def test_hidden_field_cannot_be_grouped(db_session):
    from app.models.iam import FieldSecurity

    hr = _user(db_session, permissions=["core_hr.employee.view"])
    role_id = db_session.query(RoleAssignment).filter(RoleAssignment.user_id == hr.id).one().role_id
    db_session.add(FieldSecurity(tenant_id=TENANT.tenant_id, role_id=role_id, entity="employee", field="gender", access="hidden"))
    db_session.commit()
    with pytest.raises(ReportPermissionError):
        ReportBuilder(db_session, TENANT, hr).run("headcount", {"group_by": ["gender"], "measures": [{"field": "employee_id", "agg": "count"}]})
    rows = ReportBuilder(db_session, TENANT, hr).run("headcount", {"columns": ["employee_id", "gender"]})
    assert "gender" not in rows["columns"]


def test_as_of_rejected_for_non_effective_dated_dataset(db_session):
    hr = _user(db_session, permissions=["separation.case.view"])
    with pytest.raises(ReportError):
        ReportBuilder(db_session, TENANT, hr).run("exits", {"as_of": "2026-01-01"})


def test_metrics_respect_scope(db_session):
    manager = _employee(db_session)
    _employee(db_session, manager_id=manager.id)
    everyone = metrics.compute(db_session, TENANT, "headcount")["value"]
    scoped = metrics.compute(db_session, TENANT, "headcount", scope={manager.id})["value"]
    assert scoped == 1 and everyone >= 2


# ---- scheduled report delivery ----


def test_next_run_weekly_and_monthly():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    weekly = SimpleNamespace(frequency="weekly", hour=8, day_of_week=0, day_of_month=None)
    after = datetime(2026, 9, 30, 12, tzinfo=tz)  # Wednesday
    assert schedules.next_run_after(weekly, after, tz) == datetime(2026, 10, 5, 8, tzinfo=tz).astimezone(timezone.utc)
    monthly = SimpleNamespace(frequency="monthly", hour=8, day_of_week=None, day_of_month=1)
    assert schedules.next_run_after(monthly, after, tz) == datetime(2026, 10, 1, 8, tzinfo=tz).astimezone(timezone.utc)


def test_scheduled_report_delivery_runs_as_owner_and_attaches_file(db_session, monkeypatch):
    sent = []
    monkeypatch.setattr("app.platform.comms.service.send", lambda db, tenant, **kw: sent.append(kw) or SimpleNamespace(id=uuid.uuid4()))
    owner = _user(db_session, permissions=["core_hr.employee.view"])
    _employee(db_session)
    report = SavedReport(tenant_id=TENANT.tenant_id, name="Headcount", dataset_code="headcount", definition_json={"columns": ["employee_id"]}, owner_user_id=owner.id)
    db_session.add(report)
    db_session.commit()
    schedule = schedules.create_schedule(db_session, TENANT, report, frequency="daily", hour=8, recipients=["hr@example.com"], template_key="report_delivery",
                                         now=datetime(2026, 9, 28, 1, tzinfo=timezone.utc))
    deliveries = schedules.run_due_schedules(db_session, TENANT, now=schedule.next_run_at + timedelta(minutes=1))
    assert [d.status for d in deliveries] == ["sent"]
    assert sent[0]["purpose"] == "email.outbound.reports" and sent[0]["attachments"][0]["filename"] == "Headcount.csv"
    assert schedule.next_run_at > deliveries[0].run_at
    assert schedules.run_due_schedules(db_session, TENANT, now=deliveries[0].run_at) == []  # not due again yet


def test_scheduled_delivery_failure_is_recorded(db_session):
    owner = _user(db_session, permissions=["analytics.report.view"])  # lost dataset permission
    report = SavedReport(tenant_id=TENANT.tenant_id, name="X", dataset_code="headcount", definition_json={}, owner_user_id=owner.id)
    db_session.add(report)
    db_session.commit()
    schedule = schedules.create_schedule(db_session, TENANT, report, frequency="daily", hour=8, recipients=["a@example.com"], template_key="t")
    delivery = schedules.deliver(db_session, TENANT, schedule)
    assert delivery.status == "failed" and "permission" in delivery.error


# ---- governance: AI disabled / budget cutoff / redaction / decision log ----


def _fake_gateway(monkeypatch, text="ok", usage=None):
    calls = []

    def _complete(db, tenant, **kw):
        calls.append(kw)
        return {"content": [{"type": "text", "text": text}], "usage": usage or {"input_tokens": 10, "output_tokens": 5}, "model": "test-model"}

    monkeypatch.setattr("app.platform.ai.gateway.complete", _complete)
    return calls


def test_ai_disabled_blocks_call_and_hides_features(db_session, monkeypatch):
    calls = _fake_gateway(monkeypatch)
    _patch_setting(monkeypatch, {"ai.enabled": False})
    with pytest.raises(governance.AIDisabledError):
        governance.governed_complete(db_session, TENANT, feature="copilot.chat", purpose="llm.copilot", system="s", messages=[{"role": "user", "content": "hi"}])
    assert calls == []
    flags = governance.feature_flags(db_session, TENANT)
    assert flags["enabled"] is False and not any(flags["features"].values())
    assert db_session.query(AiDecisionLog).filter(AiDecisionLog.status == "blocked").count() >= 1


def test_single_feature_or_module_can_be_disabled(db_session, monkeypatch):
    _patch_setting(monkeypatch, {"ai.features.disabled": ["agents.*", "copilot.chat"]})
    assert not governance.feature_enabled(db_session, TENANT, "copilot.chat")
    assert not governance.feature_enabled(db_session, TENANT, "agents.recruiter")
    assert governance.feature_enabled(db_session, TENANT, "performance.review_draft")


def test_bootstrap_exposes_ai_flags(client, monkeypatch):
    _patch_setting(monkeypatch, {"ai.enabled": False})
    body = client.get("/api/me/bootstrap").json()
    assert body["ai"]["enabled"] is False


def test_budget_cutoff(db_session, monkeypatch):
    calls = _fake_gateway(monkeypatch, usage={"input_tokens": 60, "output_tokens": 50})
    db_session.add(AiUsageBudget(tenant_id=TENANT.tenant_id, period=governance.current_period(), token_limit=100))
    db_session.commit()
    governance.governed_complete(db_session, TENANT, feature="copilot.chat", purpose="llm.copilot", system="s", messages=[{"role": "user", "content": "q"}])
    with pytest.raises(governance.BudgetExceededError):
        governance.governed_complete(db_session, TENANT, feature="copilot.chat", purpose="llm.copilot", system="s", messages=[{"role": "user", "content": "q"}])
    assert len(calls) == 1


def test_redaction_before_sending_and_logged(db_session, monkeypatch):
    calls = _fake_gateway(monkeypatch)
    result = governance.governed_complete(db_session, TENANT, feature="copilot.chat", purpose="llm.copilot", system="s",
                                          messages=[{"role": "user", "content": "PAN ABCDE1234F, mail x.y@example.com"}])
    sent = calls[0]["messages"][0]["content"]
    assert "ABCDE1234F" not in sent and "x.y@example.com" not in sent
    log = db_session.get(AiDecisionLog, result.decision_log_id)
    assert log.redactions_json == {"pan": 1, "email": 1} and log.model == "test-model"
    assert db_session.query(AiUsageRecord).filter(AiUsageRecord.decision_log_id == log.id).one().input_tokens == 10


# ---- copilot: RAG citations required + tool authz + drafts ----


def _policy(db_session):
    retrieval.ingest(db_session, TENANT, title="Leave Policy", body="# Casual leave\nEmployees get 12 days of casual leave per calendar year.\n\n# Sick leave\nSick leave is 10 days.")


def test_copilot_answer_has_citations(db_session, monkeypatch):
    _policy(db_session)
    _fake_gateway(monkeypatch, text="You get 12 days of casual leave per year [1].")
    user = _user(db_session, permissions=["copilot.chat.view"])
    answer = CopilotService(db_session, TENANT, user).ask("How many days of casual leave do I get per year?")
    assert answer["citations"] and answer["citations"][0]["title"] == "Leave Policy"
    assert answer.get("handover") is not True


def test_copilot_uncited_answer_is_not_shown(db_session, monkeypatch):
    _policy(db_session)
    _fake_gateway(monkeypatch, text="You get 30 days of leave.")  # no citation
    user = _user(db_session, permissions=["copilot.chat.view"])
    answer = CopilotService(db_session, TENANT, user).ask("How many days of casual leave per year?")
    assert answer["handover"] is True and "30 days" not in answer["answer"]
    assert answer["draft"]["action"] == "raise_ticket"


def test_copilot_hands_over_when_nothing_found(db_session, monkeypatch):
    calls = _fake_gateway(monkeypatch)
    user = _user(db_session, permissions=["copilot.chat.view"])
    answer = CopilotService(db_session, TENANT, user).ask("What is the parking reimbursement for electric scooters?")
    assert answer["handover"] is True and calls == []  # no retrieval hit -> no LLM call at all


def test_copilot_tool_denied_without_permission(db_session, monkeypatch):
    _fake_gateway(monkeypatch)
    user = _user(db_session, permissions=["copilot.chat.view"])  # no assets.self.view
    answer = CopilotService(db_session, TENANT, user).ask("Which assets are assigned to me? my laptop")
    assert answer["tool_calls"][0] == {"tool": "my_assets", "denied": True}


def test_copilot_tool_returns_only_callers_data(db_session, monkeypatch):
    _fake_gateway(monkeypatch, text="You have 1 open ticket.")
    from app.platform.metadata import masters
    from app.service_desk import tickets

    masters.create_value(db_session, TENANT, type_code="ticket_category", code="it_help", label_i18n={"en": "IT"})
    me = _user(db_session, permissions=["copilot.chat.view", "helpdesk.self.view"])
    other = _user(db_session, permissions=["copilot.chat.view", "helpdesk.self.view"])
    tickets.create_ticket(db_session, TENANT, category_code="it_help", subject="mine", requester_user_id=me.id)
    tickets.create_ticket(db_session, TENANT, category_code="it_help", subject="theirs", requester_user_id=other.id)
    answer = CopilotService(db_session, TENANT, me).ask("what is the status of my ticket?")
    subjects = [t["subject"] for t in answer["tool_calls"][0]["result"]["tickets"]]
    assert subjects == ["mine"]


def test_copilot_action_creates_draft_not_submission(db_session, monkeypatch):
    _fake_gateway(monkeypatch)
    from app.models.service_desk import Ticket

    user = _user(db_session, permissions=["copilot.chat.view", "helpdesk.self.create"])
    before = db_session.query(Ticket).count()
    answer = CopilotService(db_session, TENANT, user).ask("Please raise a ticket: my payslip is missing")
    assert answer["draft"]["action"] == "raise_ticket"
    assert db_session.query(Ticket).count() == before  # nothing submitted until confirm
    assert db_session.get(CopilotDraft, uuid.UUID(answer["draft"]["id"])).status == "draft"


def test_copilot_disabled(db_session, monkeypatch):
    _patch_setting(monkeypatch, {"ai.enabled": False})
    user = _user(db_session, permissions=["copilot.chat.view"])
    with pytest.raises(governance.AIDisabledError):
        CopilotService(db_session, TENANT, user).ask("hello")


def test_knowledge_audience_restriction(db_session):
    retrieval.ingest(db_session, TENANT, title="Manager handbook", body="Bonus calibration guidelines for managers.", audience_role_names=["Manager"])
    assert retrieval.search(db_session, TENANT, "bonus calibration guidelines", role_names=["Employee"]) == []
    assert retrieval.search(db_session, TENANT, "bonus calibration guidelines", role_names=["Manager"])


# ---- agents (HITL) ----


def test_agent_suggestion_applies_only_on_approval(db_session, monkeypatch):
    from app.models.job_role import JobRole

    _fake_gateway(monkeypatch, text="Senior Engineer JD")
    job = JobRole(tenant_id=TENANT.tenant_id, title="Senior Engineer", department="Eng", location="Chennai")
    db_session.add(job)
    db_session.commit()
    suggestion = agents.recruiter_jd_draft(db_session, TENANT, job.id)
    db_session.refresh(job)
    assert job.jd_text is None and suggestion.status == "pending"

    reviewer = _user(db_session, permissions=["recruitment.job.edit", "agents.suggestion.view"])
    assert suggestion.id in {s.id for s in agents.inbox(db_session, TENANT, reviewer)}
    agents.decide(db_session, TENANT, suggestion, user=reviewer, action="edit", edited_payload={"jd_text": "Edited JD"})
    db_session.refresh(job)
    assert job.jd_text == "Edited JD"
    log = db_session.get(AiDecisionLog, suggestion.decision_log_id)
    assert log.final_decision == "edited" and log.human_reviewer == reviewer.email


def test_agent_rejection_changes_nothing(db_session, monkeypatch):
    from app.models.job_role import JobRole

    _fake_gateway(monkeypatch, text="JD")
    job = JobRole(tenant_id=TENANT.tenant_id, title="Analyst")
    db_session.add(job)
    db_session.commit()
    suggestion = agents.recruiter_jd_draft(db_session, TENANT, job.id)
    reviewer = _user(db_session, permissions=["recruitment.job.edit"])
    agents.decide(db_session, TENANT, suggestion, user=reviewer, action="reject")
    db_session.refresh(job)
    assert job.jd_text is None


def test_agent_decision_requires_reviewer_permission(db_session, monkeypatch):
    _fake_gateway(monkeypatch, text="x")
    suggestion = agents.suggest(db_session, TENANT, agent="policy_checker", kind="policy_review", title="t", payload={}, reviewer_permission="helpdesk.kb.edit")
    outsider = _user(db_session, permissions=["copilot.chat.view"])
    with pytest.raises(PermissionError):
        agents.decide(db_session, TENANT, suggestion, user=outsider, action="approve")


def test_triage_never_sends_confidential_ticket(db_session):
    from app.platform.metadata import masters
    from app.service_desk import tickets

    masters.create_value(db_session, TENANT, type_code="ticket_category", code="posh_x", label_i18n={"en": "POSH"}, attributes={"confidential": True})
    ticket = tickets.create_ticket(db_session, TENANT, category_code="posh_x", subject="complaint")
    with pytest.raises(agents.AgentError):
        agents.helpdesk_triage(db_session, TENANT, ticket.id)


# ---- API ----


def test_api_ai_disabled_returns_friendly_403(client, monkeypatch):
    _patch_setting(monkeypatch, {"ai.enabled": False})
    response = client.post("/api/v1/intelligence/copilot/ask", json={"question": "hello"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "AI_DISABLED"


def test_api_datasets_listed_by_permission(client):
    response = client.get("/api/v1/intelligence/datasets")
    assert response.status_code == 200 and any(d["code"] == "headcount" for d in response.json())
