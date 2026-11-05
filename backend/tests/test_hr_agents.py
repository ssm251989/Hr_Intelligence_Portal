"""HR agent team (app/hr_agents): the HR assistant hands work to the Job / Screening /
Scheduling agents, agents hand work to each other, and every hand-off is recorded.

The model is faked at the AI gateway (platform/ai/gateway.complete) with a script per agent,
so the real LangGraph graph, the real tools and the real database rows run. Permissions are
granted by patching has_permission (one test checks the refusal path)."""

import uuid

import pytest

from app.hr_agents import graph as team_graph
from app.hr_agents.routing import looks_like_task
from app.hr_agents.tools import AgentContext
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.intelligence import AgentSuggestion
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.tenancy.context import TENANT_1_ID, TenantContext


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _text(t):
    return {"type": "text", "text": t}


def _use(tool_name, **inp):
    return {"type": "tool_use", "id": f"tu_{uuid.uuid4().hex[:10]}", "name": tool_name, "input": inp}


class Script:
    """Per-agent queues of model replies; `calls` keeps what each agent was sent."""

    def __init__(self, **queues):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.calls: list[tuple[str, list, list]] = []

    def __call__(self, db, tenant, *, purpose, system, messages, **kw):
        agent = kw.get("_feature", "").removeprefix("agents.")
        self.calls.append((agent, list(messages), [t["name"] for t in kw.get("tools", [])]))
        queue = self.queues.get(agent) or []
        content = queue.pop(0) if queue else [_text(f"{agent} done")]
        if callable(content):
            content = content(messages)
        return {"content": content, "usage": {"input_tokens": 10, "output_tokens": 5}, "model": "test-model"}


@pytest.fixture()
def db_session(_default_tenant_context):
    """Like conftest's db_session, but each session.commit() is a SAVEPOINT, so the rollback a
    tool does after a refused action undoes only that action (as in the real app), not the
    test's own rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings

    engine = create_engine(settings.APP_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture()
def user(db_session):
    u = User(email=f"agents-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Agent Tester", role="admin")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def allow(monkeypatch):
    import app.platform.iam.authz as authz

    import app.agents.service as agent_service

    monkeypatch.setattr(authz, "has_permission", lambda db, tenant, user, code: True)
    monkeypatch.setattr(agent_service, "has_permission", lambda db, tenant, user, code: True)


def _ctx(db_session, user):
    return AgentContext(db=db_session, tenant=_tenant(), user=user)


def _job_with_screened(db_session, user, n=3):
    job = JobRole(title=f"Agent Test Engineer {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", created_by=user.id)
    db_session.add(job)
    db_session.commit()
    apps = []
    for i in range(n):
        cand = Candidate(full_name=f"Cand {i}", email=f"cand{i}-{uuid.uuid4().hex[:6]}@example.com", parsed_fields={"skills": ["python"]})
        db_session.add(cand)
        db_session.commit()
        app = Application(job_role_id=job.id, candidate_id=cand.id, status="screened", composite_score=90 - i * 10)
        db_session.add(app)
        apps.append(app)
    db_session.commit()
    return job, apps


# ---------------------------------------------------------------- routing (no database)


@pytest.mark.parametrize("q, expected", [
    ("Create a job for a senior Python developer in Chennai and screen the applicants", True),
    ("Shortlist the top 3 candidates for the Java role", True),
    ("Start interview scheduling for the shortlisted candidates of Data Engineer", True),
    ("How many casual leaves do I get?", False),
    ("What is the notice period for a senior employee?", False),
    ("How many open jobs do we have?", False),  # the existing my-data tool answers this
    ("Eg1", False),
])
def test_which_questions_go_to_the_team(q, expected):
    assert looks_like_task(q) is expected


# ---------------------------------------------------------------- the team


def test_assistant_job_agent_hands_to_screening_agent(db_session, user, allow, monkeypatch):
    """HR assistant -> Job agent (creates the draft + JD) -> Screening agent -> report back."""
    import app.ai_services.jd_generator as jdg
    from app.platform.ai import gateway

    monkeypatch.setattr(jdg, "generate_jd", lambda inputs: {"title": inputs["title"], "summary": "S", "responsibilities": ["R"], "requirements": ["Q"],
                                                            "nice_to_have": [], "benefits": [], "about": "A"})
    monkeypatch.setattr("app.jobs.router._render_jd_text", lambda jd: f"JD for {jd['title']}")
    created = {}

    def job_after_create(messages):
        result = messages[-1]["content"][0]["content"]
        import json

        created["job_id"] = json.loads(result)["job_id"]
        return [_use("draft_job_description", job_id=created["job_id"])]

    script = Script(
        hr_assistant=[[_text("Starting."), _use("transfer_to_job", task="Create a Python developer job in Chennai, 3-6 years")],
                      [_text("The Job agent created the job and the Screening agent found no applications yet.")]],
        job=[[_use("create_job_draft", title="Python Developer", location="Chennai", experience_min_years=3, experience_max_years=6,
                   must_have_skills=["Python", "Django"])],
             job_after_create,
             lambda m: [_text("Job drafted with JD."), _use("transfer_to_screening", task=f"Screen applicants for job {created['job_id']}")]],
        screening=[lambda m: [_use("list_applications", job_id=created["job_id"])], [_text("No applications yet.")]],
    )
    monkeypatch.setattr(gateway, "complete", script)

    out = team_graph.run_team(_ctx(db_session, user), "Create a Python developer job in Chennai and screen the applicants")

    job = db_session.get(JobRole, uuid.UUID(created["job_id"]))
    assert job is not None and job.status == "ready_for_publishing" and job.jd_text == "JD for Python Developer"
    assert job.technical_skills_must_have == ["Python", "Django"] and job.created_by == user.id
    hops = [(m["from"], m["to"], m["kind"]) for m in out["trace"]]
    assert hops == [("hr_assistant", "job", "task"), ("job", "hr_assistant", "result"), ("job", "screening", "task"),
                    ("screening", "hr_assistant", "result")]
    assert [a["name"] for a in out["agents_used"]] == ["job", "screening"]
    assert out["answer"].startswith("The Job agent created")
    # the HR assistant got both agents' reports in one tool_result for its transfer
    last_supervisor_msgs = [c for c in script.calls if c[0] == "hr_assistant"][-1][1]
    report = last_supervisor_msgs[-1]["content"][0]["content"]
    assert "Report from the Job agent" in report and "Report from the Screening agent" in report
    assert out["links"] and out["links"][0]["path"] == f"/jobs/{created['job_id']}"


def test_screening_agent_proposes_a_shortlist_and_only_hr_approval_shortlists(db_session, user, allow, monkeypatch):
    from app.agents.service import decide
    from app.hr_agents import approvals  # noqa: F401
    from app.platform.ai import gateway

    job, apps = _job_with_screened(db_session, user)
    started = []
    monkeypatch.setattr("app.shortlisting.router._start_scheduling", lambda db, application, u: started.append(application.id))
    monkeypatch.setattr("app.shortlisting.service._salary_after_shortlist", lambda db, application, actor: None)
    script = Script(
        hr_assistant=[[_use("transfer_to_screening", task=f"Shortlist the top 2 for job {job.id}")], [_text("Approval card ready.")]],
        screening=[[_use("top_candidates", job_id=str(job.id), n=2)],
                   [_use("propose_shortlist", job_id=str(job.id), application_ids=[str(apps[0].id), str(apps[1].id)], reason="Top scores")],
                   [_text("Proposed 2 for HR approval.")]],
    )
    monkeypatch.setattr(gateway, "complete", script)

    ctx = _ctx(db_session, user)
    out = team_graph.run_team(ctx, f"Shortlist the top 2 for job {job.id}")

    assert len(out["suggestions"]) == 1
    card = db_session.get(AgentSuggestion, uuid.UUID(out["suggestions"][0]["id"]))
    assert card.kind == "agent_shortlist" and card.status == "pending"
    db_session.refresh(apps[0])
    assert apps[0].status == "screened"  # nothing changed before HR approves

    decide(db_session, _tenant(), card, user=user, action="approve")
    for a in apps[:2]:
        db_session.refresh(a)
        assert a.status == "hr_selected"
    db_session.refresh(apps[2])
    assert apps[2].status == "screened"
    assert set(started) == {apps[0].id, apps[1].id}


def test_a_tool_without_permission_is_refused_and_reported(db_session, user, monkeypatch):
    import app.platform.iam.authz as authz
    from app.platform.ai import gateway

    monkeypatch.setattr(authz, "has_permission", lambda db, tenant, u, code: code != "recruitment.job.create")
    seen = {}

    def job_reads_error(messages):
        seen["result"] = messages[-1]["content"][0]["content"]
        return [_text("You don't have permission to create jobs.")]

    script = Script(hr_assistant=[[_use("transfer_to_job", task="Create a job")], [_text("You need an HR admin to create jobs.")]],
                    job=[[_use("create_job_draft", title="Should not exist")], job_reads_error])
    monkeypatch.setattr(gateway, "complete", script)
    before = db_session.query(JobRole).filter(JobRole.title == "Should not exist").count()

    out = team_graph.run_team(_ctx(db_session, user), "Create a job for a tester")

    assert "recruitment.job.create" in seen["result"]
    assert db_session.query(JobRole).filter(JobRole.title == "Should not exist").count() == before
    assert out["answer"] == "You need an HR admin to create jobs."


def test_hop_limit_stops_endless_hand_offs(db_session, user, allow, monkeypatch):
    from app.platform.ai import gateway

    class PingPong:
        def __call__(self, db, tenant, *, purpose, system, messages, **kw):
            agent = kw["_feature"].removeprefix("agents.")
            tools = [t["name"] for t in kw.get("tools", [])]
            if agent == "hr_assistant":
                content = [_use("transfer_to_screening", task="go")] if tools else [_text("Stopped.")]
            else:
                target = "transfer_to_scheduling" if agent == "screening" else "transfer_to_screening"
                content = [_use(target, task="your turn")]
            return {"content": content, "usage": {}}

    monkeypatch.setattr(gateway, "complete", PingPong())
    out = team_graph.run_team(_ctx(db_session, user), "Screen and schedule everything")
    assert out["answer"] == "Stopped."
    assert len([m for m in out["trace"] if m["kind"] == "task" and m["from"] != "hr_assistant"]) <= team_graph.MAX_HOPS


def test_hr_assistant_question_goes_to_team_and_policy_question_does_not(db_session, user, allow, monkeypatch):
    from app.copilot.service import CopilotService
    from app.platform.ai import gateway

    script = Script(hr_assistant=[[_text("Here is what the team found.")]])
    monkeypatch.setattr(gateway, "complete", script)
    svc = CopilotService(db_session, _tenant(), user)

    reply = svc.ask("Find the top candidates for the Java developer role")
    assert reply["answer"] == "Here is what the team found."
    assert "agents" in reply and reply["agents"]["trace"] == []
    assert script.calls and script.calls[0][0] == "hr_assistant"

    calls_before = len(script.calls)
    monkeypatch.setattr("app.copilot.retrieval.search", lambda *a, **k: [])
    policy = svc.ask("What is the notice period for a senior employee?")
    assert "agents" not in policy and len(script.calls) == calls_before


# ---------------------------------------------------------------- hiring-to-exit agents (Part 25b)


def _app_in(db_session, user, status, **extra):
    job = JobRole(title=f"E2E Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", created_by=user.id,
                  salary_band_min=800000, salary_band_max=1200000)
    db_session.add(job)
    db_session.commit()
    cand = Candidate(full_name=f"Priya {uuid.uuid4().hex[:4]}", email=f"priya-{uuid.uuid4().hex[:6]}@example.com")
    db_session.add(cand)
    db_session.commit()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status=status, **extra)
    db_session.add(app)
    db_session.commit()
    return app, cand


@pytest.mark.parametrize("q, expected", [
    ("Check Priya's salary and send her the documents form", True),
    ("Propose joining dates for Arun", True),
    ("Who joins this week for onboarding?", True),
    ("What blocks Ravi's relieving letter?", True),
    ("Show me the open exits", True),
    ("Show my offer letter", False),  # the asker's own data: self-service path
])
def test_hiring_to_exit_questions_go_to_the_team(q, expected):
    assert looks_like_task(q) is expected


def test_every_agent_is_registered_with_a_feature_and_unique_tools():
    from app.hr_agents.agents import AGENTS, SUPERVISOR, tool_schemas
    from app.platform.ai.governance import AI_FEATURES

    assert set(AGENTS) == {SUPERVISOR, "job", "screening", "scheduling", "salary", "bgv", "offer", "onboarding", "exit", "policy"}
    for name, spec in AGENTS.items():
        assert spec.feature in AI_FEATURES, name
        names = [t["name"] for t in tool_schemas(spec)]
        assert len(names) == len(set(names)), name
        assert all(t in AGENTS for t in spec.hands_off_to)
    assert set(AGENTS[SUPERVISOR].hands_off_to) == set(AGENTS) - {SUPERVISOR}


def test_salary_agent_hands_to_bgv_agent_and_salary_changes_only_on_approval(db_session, user, allow, monkeypatch):
    """HR assistant -> Salary agent (finds Priya, proposes approve at 11L) -> Documents & BGV agent -> report."""
    from app.agents.service import decide
    from app.hr_agents import approvals  # noqa: F401
    from app.platform.ai import gateway

    app, cand = _app_in(db_session, user, "salary_above_band", expected_salary=1300000,
                        salary_check={"state": "needs_approval", "expected": 1300000, "band_min": 800000, "band_max": 1200000})
    after = []
    monkeypatch.setattr("app.recruitment.joining_docs.after_salary_approved", lambda db, tenant, a, actor: after.append(a.id))
    script = Script(
        hr_assistant=[[_use("transfer_to_salary", task=f"Sort out {cand.full_name}'s salary, then the documents")],
                      [_text("The Salary agent proposed 11 LPA for approval; the Documents agent will chase documents after that.")]],
        salary=[[_use("find_candidate", **{"name": cand.full_name})],
                [_use("salary_queue")],
                [_use("propose_salary_decision", application_id=str(app.id), decision="approve", amount=1100000, reason="Inside band, strong interview")],
                [_text("Proposed approve at 11,00,000."), _use("transfer_to_bgv", task=f"After approval, collect documents for {app.id}")]],
        bgv=[[_use("documents_status", application_id=str(app.id))], [_text("Documents not requested yet; they go out once salary is approved.")]],
    )
    monkeypatch.setattr(gateway, "complete", script)

    out = team_graph.run_team(_ctx(db_session, user), f"Sort out {cand.full_name}'s salary and then the documents")

    salary_calls = [c for c in script.calls if c[0] == "salary"]
    found = salary_calls[1][1][-1]["content"][0]["content"]
    assert str(app.id) in found and "salary_above_band" in found
    queue = salary_calls[2][1][-1]["content"][0]["content"]
    assert str(app.id) in queue and "needs_approval" in queue
    hops = [(m["from"], m["to"], m["kind"]) for m in out["trace"]]
    assert hops == [("hr_assistant", "salary", "task"), ("salary", "hr_assistant", "result"), ("salary", "bgv", "task"), ("bgv", "hr_assistant", "result")]
    assert len(out["suggestions"]) == 1
    card = db_session.get(AgentSuggestion, uuid.UUID(out["suggestions"][0]["id"]))
    assert card.kind == "agent_salary_decision" and card.payload_json["by_agent"] == "salary" and card.reviewer_permission == "recruitment.salary.edit"
    db_session.refresh(app)
    assert app.status == "salary_above_band" and app.approved_salary is None

    decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(app)
    assert app.status == "salary_approved" and float(app.approved_salary) == 1100000 and after == [app.id]


def test_bgv_decision_card_clears_bgv_and_offer_agent_validates_dates(db_session, user, allow, monkeypatch):
    from datetime import date, timedelta

    from app.agents.service import decide
    from app.hr_agents import approvals  # noqa: F401
    from app.platform.ai import gateway

    app, cand = _app_in(db_session, user, "bgv_pending")
    monkeypatch.setattr("app.recruitment.joining_dates.after_bgv_passed", lambda *a, **k: None)
    seen = {}
    d = [(date.today() + timedelta(days=n)).isoformat() for n in (10, 12, 14)]

    def offer_sees_error(messages):
        seen["bad_dates"] = messages[-1]["content"][0]["content"]
        return [_use("propose_joining_dates", application_id=str(app.id), dates=d, note="Pick one")]

    script = Script(
        hr_assistant=[[_use("transfer_to_bgv", task=f"BGV for {app.id} came back clean")], [_text("Done.")],
                      [_use("transfer_to_offer", task=f"Offer joining dates to {app.id}")], [_text("Dates proposed for approval.")]],
        bgv=[[_use("propose_bgv_decision", application_id=str(app.id), decision="passed")], [_text("Proposed BGV passed.")]],
        offer=[[_use("propose_joining_dates", application_id=str(app.id), dates=d[:2])], offer_sees_error, [_text("Proposed 3 dates.")]],
    )
    monkeypatch.setattr(gateway, "complete", script)
    ctx = _ctx(db_session, user)
    out = team_graph.run_team(ctx, f"BGV for {cand.full_name} came back clean")
    card = db_session.get(AgentSuggestion, uuid.UUID(out["suggestions"][0]["id"]))
    assert card.kind == "agent_bgv_decision"
    db_session.refresh(app)
    assert app.status == "bgv_pending"
    decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(app)
    assert app.status == "bgv_cleared"

    out2 = team_graph.run_team(_ctx(db_session, user), f"Propose joining dates for {cand.full_name}")
    assert "exactly three" in seen["bad_dates"]
    card2 = db_session.get(AgentSuggestion, uuid.UUID(out2["suggestions"][0]["id"]))
    assert card2.kind == "agent_joining_dates" and card2.payload_json["dates"] == d
    decide(db_session, _tenant(), card2, user=user, action="approve")
    db_session.refresh(app)
    from app.recruitment import joining_dates

    assert joining_dates.info(app)["proposed"] == d


def test_a_card_whose_service_refuses_stays_pending_with_the_reason(db_session, user, allow, monkeypatch):
    """HR approves a salary card after someone already rejected the candidate on the Salary screen."""
    from app.agents.service import AgentError, decide
    from app.hr_agents import approvals  # noqa: F401
    from app.hr_agents.tools_e2e import propose_salary_decision

    app, _ = _app_in(db_session, user, "salary_above_band", expected_salary=1300000)
    out = propose_salary_decision(_ctx(db_session, user), str(app.id), "approve", amount=1100000)
    card = db_session.get(AgentSuggestion, uuid.UUID(out["approval_card_id"]))
    app.status = "salary_rejected"
    db_session.commit()
    with pytest.raises(AgentError, match="not waiting for a salary decision"):
        decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(card)
    assert card.status == "pending"


def test_onboarding_exit_and_policy_tools_run(db_session, user, allow, monkeypatch):
    from app.hr_agents.tools import run_tool
    from app.hr_agents.tools_e2e import EXIT_TOOLS, ONBOARDING_TOOLS, POLICY_TOOLS

    ctx = _ctx(db_session, user)
    by = {t.name: t for t in EXIT_TOOLS + ONBOARDING_TOOLS + POLICY_TOOLS}
    assert "joiners" in run_tool(ctx, by["onboarding_board"], {})
    assert "exits" in run_tool(ctx, by["open_exits"], {})
    assert "error" in run_tool(ctx, by["propose_mark_joined"], {"case_id": str(uuid.uuid4())})
    assert "error" in run_tool(ctx, by["exit_detail"], {"separation_id": "not-an-id"})

    class Hit:
        document_title, heading, text = "Leave Policy", "Notice", "Senior employees serve 60 days notice."

    monkeypatch.setattr("app.copilot.retrieval.search", lambda *a, **k: [Hit()])
    monkeypatch.setattr("app.platform.iam.roles.role_names_for", lambda *a, **k: ["hr"])
    res = run_tool(ctx, by["search_handbook"], {"question": "notice period senior"})
    assert res["passages"][0]["source"] == "Leave Policy - Notice"


def test_people_without_an_hr_permission_never_reach_the_team(db_session, user, monkeypatch):
    import app.platform.iam.authz as authz
    from app.copilot.service import CopilotService
    from app.platform.ai import gateway

    monkeypatch.setattr(authz, "has_permission", lambda db, tenant, u, code: False)
    script = Script()
    monkeypatch.setattr(gateway, "complete", script)
    svc = CopilotService(db_session, _tenant(), user)
    assert svc._agent_team(None, "Shortlist the top 3 candidates for the Java role") is None
    assert not [c for c in script.calls if c[0] == "hr_assistant"]
