"""Part 29: HR Automation runs on its agents ("agent prepares, HR approves").

Covers the steps added on top of Part 26: the Screening agent's shortlist card, the Scheduling agent,
the Exit agent's resignation card, the two new card appliers, the agent timeline of automatic steps,
and the new defaults (Autopilot on, every decision rule off)."""

import uuid
from datetime import date, datetime, timedelta, timezone

from app.audit.service import log_action
from app.hr_agents.autopilot import hiring, people, runner
from app.hr_agents.autopilot.core import Run
from app.models.intelligence import AgentSuggestion

from tests.test_autopilot import _acts, _app, _tenant, allow, conf, db_session, user  # noqa: F401 -- shared fixtures


def _card(db, entity_id, kind):
    return db.query(AgentSuggestion).filter(AgentSuggestion.entity_id == entity_id, AgentSuggestion.kind == kind).one_or_none()


# ---------------------------------------------------------------- defaults


def test_new_companies_start_with_the_agents_on_and_every_decision_rule_off():
    from app.platform.settings.registry import get_definition

    assert get_definition("autopilot.enabled").default is True
    for agent in ("screening", "scheduling", "salary", "documents", "bgv", "offer", "onboarding", "exit"):
        assert get_definition(f"autopilot.{agent}.enabled").default is True
    for r in ("shortlist_min_score", "salary_max_over_band_pct"):
        assert get_definition(f"autopilot.rules.{r}").default == 0
    for r in ("documents_auto_approve", "bgv_auto_assign_vendor", "bgv_auto_pass_clear_report", "joining_dates_auto", "mark_joined_when_ready", "exit_letters_auto"):
        assert get_definition(f"autopilot.rules.{r}").default is False


# ---------------------------------------------------------------- Screening agent: shortlist card


def test_screened_candidate_above_the_threshold_gets_a_shortlist_card_and_below_does_not(db_session, user, allow, conf, monkeypatch):
    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 70)
    strong = _app(db_session, user, "screened", composite_score=82, score_breakdown={})
    weak = _app(db_session, user, "screened", composite_score=55, score_breakdown={})
    knocked = _app(db_session, user, "screened", composite_score=90, score_breakdown={"knocked_out": True})

    for a in (strong, weak, knocked):
        hiring.shortlist_rule(db_session, _tenant(), a, Run("event", "ai_screening_scored"))

    card = _card(db_session, strong.id, "agent_shortlist")
    assert card is not None and card.payload_json["by_agent"] == "autopilot.screening"
    assert card.payload_json["candidates"] == [{"application_id": str(strong.id), "name": card.payload_json["candidate"], "score": 82}]
    assert _card(db_session, weak.id, "agent_shortlist") is None and _card(db_session, knocked.id, "agent_shortlist") is None
    db_session.refresh(strong)
    assert strong.status == "screened"  # nothing decided: HR approves the card

    # a second scoring event does not raise a second card or a second timeline line
    hiring.shortlist_rule(db_session, _tenant(), strong, Run("event", "score_recalculated"))
    assert len(_acts(db_session, entity_id=strong.id, action="propose_shortlist")) == 1


def test_a_job_with_its_own_automatic_shortlisting_is_left_to_it(db_session, user, allow, conf, monkeypatch):
    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 50)
    app = _app(db_session, user, "screened", composite_score=90, score_breakdown={})
    from app.models.job_role import JobRole

    job = db_session.get(JobRole, app.job_role_id)
    job.shortlisting_json = {"auto_shortlist": True}
    db_session.commit()
    assert hiring.shortlist_rule(db_session, _tenant(), app, Run("event", "ai_screening_scored")) is None
    assert _card(db_session, app.id, "agent_shortlist") is None


# ---------------------------------------------------------------- Scheduling agent


def test_manual_scheduling_job_gets_a_send_times_card_and_approving_it_sends(db_session, user, allow, conf, monkeypatch):
    from app.agents.service import decide
    from app.interview_scheduling import automation

    app = _app(db_session, user, "hr_selected")
    calls = []
    monkeypatch.setattr(automation, "start", lambda db, tenant, a, actor, *, trigger, force=False: calls.append((a.id, trigger, force, actor.email))
                        or {"outcome": "started", "reason": None})

    t = _tenant()
    runner.run_events(db_session, t)  # first run sets the cursor
    log_action(db_session, "application", app.id, automation.MANUAL_MODE_ACTION, "system", {"trigger": "manual_shortlist"})
    out = runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert out["handled"] == 1
    card = _card(db_session, app.id, "agent_interview_send")
    assert card is not None and card.reviewer_permission == "recruitment.interview.edit"

    decide(db_session, t, card, user=user, action="approve")
    assert calls == [(app.id, "send_now", True, user.email)]
    assert card.status == "approved"


def test_send_times_card_stays_pending_when_sending_fails(db_session, user, allow, conf, monkeypatch):
    import pytest

    from app.agents.service import AgentError, decide
    from app.interview_scheduling import automation

    app = _app(db_session, user, "hr_selected")
    hiring.scheduling(db_session, _tenant(), app, Run("event", automation.MANUAL_MODE_ACTION))
    card = _card(db_session, app.id, "agent_interview_send")
    monkeypatch.setattr(automation, "start", lambda *a, **k: {"outcome": "problem", "reason": "No interviewer in the job's pool."})
    with pytest.raises(AgentError, match="No interviewer"):
        decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.rollback()
    db_session.refresh(card)
    assert card.status == "pending"


# ---------------------------------------------------------------- timeline of automatic steps


def test_automatic_steps_show_on_the_agent_timeline(db_session, user, allow, conf):
    app = _app(db_session, user, "interview_scheduled")
    t = _tenant()
    runner.run_events(db_session, t)
    for action in ("interview_scheduling_started", "offer_signed"):
        log_action(db_session, "application", app.id, action, "system", {})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    rows = {a.action: a for a in _acts(db_session, entity_id=app.id)}
    assert rows["step_interview_scheduling_started"].agent == "scheduling" and rows["step_interview_scheduling_started"].outcome == "done"
    assert rows["step_offer_signed"].agent == "offer" and "signed the offer" in rows["step_offer_signed"].summary


# ---------------------------------------------------------------- Exit agent: resignation card


def _resignation(db_session, *, notice=30, requested=None):
    from app.core_hr import employees as employees_service
    from app.models.service_desk import Separation

    e = employees_service.create_employee(db_session, _tenant(), first_name="Ravi", last_name="Iyer", status="on_notice")
    s = Separation(tenant_id=_tenant().tenant_id, employee_id=e.id, separation_type="resignation", initiated_by="hr@example.com",
                   submitted_on=date.today(), notice_period_days=notice, requested_lwd=requested, status="submitted")
    db_session.add(s)
    db_session.commit()
    return s


def test_resignation_gets_an_approval_card_with_the_notice_period_date(db_session, user, allow, conf, monkeypatch):
    from app.agents.service import decide
    from app.service_desk import separations

    monkeypatch.setattr("app.employees.self_service.needs_manager", lambda db, tenant, s: None)
    s = _resignation(db_session, notice=30, requested=date.today() + timedelta(days=10))
    assert people.resignations(db_session, _tenant(), Run("schedule")) == 1
    assert people.resignations(db_session, _tenant(), Run("schedule")) == 0  # once, not every hour
    card = _card(db_session, s.id, "agent_resignation_approve")
    assert card.payload_json["last_working_day"] == (date.today() + timedelta(days=30)).isoformat()
    assert "short of the notice period" in card.payload_json["note"]

    approved = []
    monkeypatch.setattr(separations, "approve_lwd", lambda db, tenant, sep, *, lwd, actor, waived_days=0, buyout_days=0:
                        approved.append((sep.id, lwd, actor, waived_days)) or type("S", (), {"status": "approved", "approved_lwd": lwd})())
    edited = {**card.payload_json, "last_working_day": (date.today() + timedelta(days=20)).isoformat(), "waived_days": 10}
    decide(db_session, _tenant(), card, user=user, action="edit", edited_payload=edited)
    assert approved == [(s.id, date.today() + timedelta(days=20), user.email, 10)]


def test_resignation_waiting_for_the_manager_is_left_alone(db_session, user, allow, conf, monkeypatch):
    monkeypatch.setattr("app.employees.self_service.needs_manager", lambda db, tenant, s: object())
    s = _resignation(db_session)
    assert people.resignations(db_session, _tenant(), Run("schedule")) == 0
    assert _card(db_session, s.id, "agent_resignation_approve") is None


def test_bad_date_on_an_edited_resignation_card_is_a_plain_error(db_session, user, allow, conf, monkeypatch):
    import pytest

    from app.agents.service import AgentError, decide

    monkeypatch.setattr("app.employees.self_service.needs_manager", lambda db, tenant, s: None)
    s = _resignation(db_session)
    people.resignations(db_session, _tenant(), Run("schedule"))
    card = _card(db_session, s.id, "agent_resignation_approve")
    with pytest.raises(AgentError, match="YYYY-MM-DD"):
        decide(db_session, _tenant(), card, user=user, action="edit", edited_payload={**card.payload_json, "last_working_day": "next friday"})


def test_agents_page_waiting_and_journey(client, db_session, conf, monkeypatch):
    """GET /waiting lists only the agents' cards; GET /journey/<id> is the candidate's agent timeline."""
    from app.agents.service import suggest

    monkeypatch.setattr("app.hr_agents.autopilot_router.has_permission", lambda db, tenant, user, code: True)
    monkeypatch.setattr("app.agents.service.has_permission", lambda db, tenant, user, code: True)
    t = _tenant()
    eid = uuid.uuid4()
    suggest(db_session, t, agent="recruiter", kind="agent_shortlist", title="Shortlist X", payload={"by_agent": "autopilot.screening"},
            reviewer_permission="recruitment.shortlisting.edit", entity_type="application", entity_id=eid)
    suggest(db_session, t, agent="recruiter", kind="jd_draft", title="JD draft", payload={}, reviewer_permission="recruitment.job.edit",
            entity_type="job_role", entity_id=uuid.uuid4())
    r = client.get("/api/v1/ui/autopilot/waiting")
    assert r.status_code == 200, r.text
    kinds = [i["kind"] for i in r.json()["items"]]
    assert "agent_shortlist" in kinds and "jd_draft" not in kinds
    r = client.get(f"/api/v1/ui/autopilot/journey/{eid}")
    assert r.status_code == 200 and r.json() == {"items": []}
