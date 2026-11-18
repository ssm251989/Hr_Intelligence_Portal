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
    from app.models.job_role import JobRole

    for a in (strong, weak, knocked):  # these jobs do not use their own automatic shortlisting, whatever the company saved
        db_session.get(JobRole, a.job_role_id).shortlisting_json = {"auto_shortlist": False}
    db_session.commit()

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


def test_shortlist_rule_on_but_not_decided_still_gives_hr_the_card(db_session, user, allow, conf, monkeypatch):
    """PART 26.2 b: with the shortlist rule on, a job that shortlists by hand (its own setting wins) got NOTHING for a
    96-score candidate - no decision and no card. Now the card comes, exactly as with the rule off."""
    from app.models.job_role import JobRole

    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 60)
    conf["autopilot.rules.shortlist_min_score"] = 70
    app = _app(db_session, user, "screened", composite_score=96, score_breakdown={})
    db_session.get(JobRole, app.job_role_id).shortlisting_json = {"auto_shortlist": False}  # this job shortlists by hand
    db_session.commit()

    assert hiring.shortlist_rule(db_session, _tenant(), app, Run("event", "ai_screening_scored")) == "proposed"
    db_session.refresh(app)
    assert app.status == "screened"  # not decided
    assert _card(db_session, app.id, "agent_shortlist") is not None


def _fresh_cursor(db_session, t):
    from app.models.autopilot import AutopilotState

    db_session.query(AutopilotState).filter(AutopilotState.tenant_id == t.tenant_id, AutopilotState.key == runner.CURSOR).delete()
    db_session.commit()
    runner.run_events(db_session, t)  # first run only sets the cursor


def test_salary_routed_to_hr_is_not_written_as_approved_and_is_proposed_once(db_session, user, allow, conf):
    """PART 26.2 c: a candidate 20% over the band read "salary ... was approved" on the timeline (the check's routing
    event `salary_auto_decided` is logged for every outcome) and "proposed a counter" twice (form answer + check)."""
    t = _tenant()
    _fresh_cursor(db_session, t)
    app = _app(db_session, user, "salary_above_band", expected_salary=1440000,
               salary_check={"state": "flagged", "expected": 1440000, "band_max": 1200000})
    log_action(db_session, "application", app.id, "salary_checked", "candidate form", {"state": "flagged"})
    log_action(db_session, "application", app.id, "salary_auto_decided", "candidate form",
               {"state": "flagged", "previous_status": "interview_selected", "new_status": "salary_above_band"})
    log_action(db_session, "application", app.id, "salary_form_answered", "candidate", {})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))

    assert _acts(db_session, entity_id=app.id, action="step_salary_auto_decided") == []
    assert len(_acts(db_session, entity_id=app.id, action="propose_salary")) == 1


def test_salary_approved_by_the_company_rule_is_on_the_timeline(db_session, user, allow, conf):
    t = _tenant()
    _fresh_cursor(db_session, t)
    app = _app(db_session, user, "salary_approved", expected_salary=1000000, approved_salary=1000000)
    log_action(db_session, "application", app.id, "salary_auto_decided", "candidate form",
               {"state": "in_band", "previous_status": "interview_selected", "new_status": "salary_approved"})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert len(_acts(db_session, entity_id=app.id, action="step_salary_auto_decided")) == 1


def test_approving_an_agent_card_in_a_fresh_process_applies_it(db_session, user, allow, conf, monkeypatch):
    """PART 26.2 c: after a restart nothing had imported app.hr_agents.approvals yet, so approving the Salary agent's
    counter card marked it approved and did NOTHING (no counter, no email). decide() now loads the appliers itself."""
    import sys

    from app.agents import service as agents

    applied = []
    monkeypatch.setattr("app.recruitment.salary_auto.decide", lambda db, tenant, a, **kw: applied.append(kw) or {"status": "salary_above_band"})
    app = _app(db_session, user, "salary_above_band", expected_salary=1440000,
               salary_check={"state": "flagged", "expected": 1440000, "band_max": 1200000})
    hiring.salary(db_session, _tenant(), app, Run("event", "salary_checked"))
    c = _card(db_session, app.id, "agent_salary_decision")

    # a fresh process: no agent appliers registered, the module not imported yet
    monkeypatch.setattr(agents, "_APPLIERS", {k: v for k, v in agents._APPLIERS.items() if not k.startswith("agent_")})
    monkeypatch.delitem(sys.modules, "app.hr_agents.approvals", raising=False)
    import app.hr_agents as package

    monkeypatch.delattr(package, "approvals", raising=False)
    agents.decide(db_session, _tenant(), c, user=user, action="approve")
    assert applied and applied[0]["decision"] == "counter" and applied[0]["amount"] == 1200000


def test_documents_upload_and_submit_events_give_one_card_and_one_timeline_line(db_session, user, allow, conf, monkeypatch):
    """PART 26.2 d: each upload (document_uploaded) and the final submit (documents_submitted) both woke the Documents
    agent, so the timeline said "All documents ... are in" twice."""
    from app.recruitment import joining_docs

    app = _app(db_session, user, "salary_approved")
    monkeypatch.setattr(joining_docs, "status", lambda db, tenant, a: {"items": [{"label": "PAN card", "level": "amber"}], "missing": [],
                                                                      "all_received": True, "all_approved": False, "reds": 0, "ambers": 1})
    monkeypatch.setattr(joining_docs, "cross_check", lambda db, tenant, a: [])
    assert hiring.documents(db_session, _tenant(), app, Run("event", "document_uploaded")) == "proposed"
    assert hiring.documents(db_session, _tenant(), app, Run("event", "documents_submitted")) is None
    assert len(_acts(db_session, entity_id=app.id, action="propose_documents")) == 1


def test_bgv_vendor_gets_the_check_names_by_rule_and_by_card(db_session, user, allow, conf, monkeypatch):
    """PART 26.2 e: a vendor's checks are stored as {"check", "price"}; the BGV agent passed those rows to vendors.assign
    (TypeError: unhashable type: 'dict'), so no BGV could go to a vendor - neither by rule nor by approving the card."""
    from app.agents import service as agents
    from app.bgv import vendors
    from app.models.agency import RecruitmentAgency

    db_session.add(RecruitmentAgency(name=f"Rule Vendor {uuid.uuid4().hex[:4]}", agency_type="bgv", contact_email="v@example.com", active=True,
                                     bgv_checks_json=[{"check": "education", "price": 700}, {"check": "employment", "price": 800}], turnaround_days=1))
    db_session.commit()
    sent = []
    monkeypatch.setattr(vendors, "assign", lambda db, tenant, a, **kw: sent.append(kw["checks"]) or {})

    by_rule = _app(db_session, user, "bgv_requested")
    conf["autopilot.rules.bgv_auto_assign_vendor"] = True
    assert hiring.bgv_assign(db_session, _tenant(), by_rule, Run("event", "bgv_requested")) == "decided"

    conf["autopilot.rules.bgv_auto_assign_vendor"] = False
    by_card = _app(db_session, user, "bgv_requested")
    assert hiring.bgv_assign(db_session, _tenant(), by_card, Run("event", "bgv_requested")) == "proposed"
    c = _card(db_session, by_card.id, "agent_bgv_assign")
    c.payload_json = {**c.payload_json, "checks": [{"check": "education", "price": 700}]}  # a card made before the fix
    db_session.commit()
    agents.decide(db_session, _tenant(), c, user=user, action="approve")
    assert sent[0] == ["education", "employment"] and sent[1] == ["education"]


def test_bgv_passed_twice_gives_one_joining_dates_card_and_one_line(db_session, user, allow, conf):
    """PART 26.2 e: bgv_report calls the Offer agent, then the bgv_passed event calls it again -> the timeline said
    "proposed joining dates" twice."""
    app = _app(db_session, user, "bgv_cleared", notice=30)
    assert hiring.offer(db_session, _tenant(), app, Run("event", "bgv_vendor_report_received")) == "proposed"
    assert hiring.offer(db_session, _tenant(), app, Run("event", "bgv_passed")) is None
    assert len(_acts(db_session, entity_id=app.id, action="propose_joining_dates")) == 1


def test_briefing_asks_for_plain_text_and_no_invented_ages(db_session, user, monkeypatch):
    """PART 26.2 i: the briefing came back in Markdown (shown and emailed as plain text) and said approvals were
    "all over 48h old" - the data has no ages."""
    from app.hr_agents.autopilot import briefing
    from app.platform.ai import governance

    seen = {}
    monkeypatch.setattr(governance, "governed_complete", lambda db, tenant, **kw: seen.update(kw) or type("R", (), {"text": "- one"})())
    briefing.compose(db_session, _tenant(), user, {"approvals_waiting": [], "approvals_count": 0, "escalated": [], "decided": [],
                                                   "interviews_today": 0, "joiners_next_7_days": [], "leavers_next_7_days": 0, "autopilot_last_24h": {}})
    assert "no Markdown" in seen["system"] and "Never add ages" in seen["system"]


def test_screening_agent_switched_off_prepares_no_shortlist(db_session, user, allow, conf, monkeypatch):
    """PART 26.2 j: with autopilot.screening.enabled off, a 96-score candidate still got a shortlist card (the
    ai_screening_scored event calls shortlist_rule, which never checked the switch)."""
    from app.models.job_role import JobRole

    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 60)
    conf["autopilot.screening.enabled"] = False
    app = _app(db_session, user, "screened", composite_score=96, score_breakdown={})
    db_session.get(JobRole, app.job_role_id).shortlisting_json = {"auto_shortlist": False}
    db_session.commit()
    assert hiring.shortlist_rule(db_session, _tenant(), app, Run("event", "ai_screening_scored")) is None
    assert _card(db_session, app.id, "agent_shortlist") is None


def test_screening_done_by_the_app_is_on_the_journey_and_still_reaches_the_shortlist_card(db_session, user, allow, conf, monkeypatch):
    """PART 29.3 b: the Journey started at "shortlist prepared" - the app screens on apply by itself, so the agent never
    wrote "screened". ai_screening_scored is now a timeline step AND still goes to the shortlist rule."""
    from app.models.job_role import JobRole

    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 60)
    t = _tenant()
    _fresh_cursor(db_session, t)
    app = _app(db_session, user, "screened", composite_score=82, score_breakdown={})
    db_session.get(JobRole, app.job_role_id).shortlisting_json = {"auto_shortlist": False}
    db_session.commit()
    log_action(db_session, "application", app.id, "ai_screening_scored", "system", {})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    step = _acts(db_session, entity_id=app.id, action="step_ai_screening_scored")
    assert len(step) == 1 and "was screened: score 82" in step[0].summary
    assert _card(db_session, app.id, "agent_shortlist") is not None


def test_events_while_autopilot_is_off_are_not_replayed_when_it_is_switched_on(db_session, user, allow, conf, monkeypatch):
    """PART 29.3 k / 26.2 j: an application screened while the master switch was off got a shortlist card a minute
    after the switch went back on - the cursor stood still while off, so the events were replayed."""
    from app.models.job_role import JobRole

    monkeypatch.setattr("app.recruitment.scoring.engine.company_threshold", lambda db, tenant: 60)
    t = _tenant()
    _fresh_cursor(db_session, t)
    conf["autopilot.enabled"] = False
    app = _app(db_session, user, "screened", composite_score=96, score_breakdown={})
    db_session.get(JobRole, app.job_role_id).shortlisting_json = {"auto_shortlist": False}
    db_session.commit()
    log_action(db_session, "application", app.id, "ai_screening_scored", "system", {})
    assert runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1)) == {"skipped": "autopilot off"}
    conf["autopilot.enabled"] = True
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=2))
    assert _card(db_session, app.id, "agent_shortlist") is None
