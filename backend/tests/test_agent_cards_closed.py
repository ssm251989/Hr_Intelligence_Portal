"""Leftover approval cards are closed (owner decision 2026-11-19, PART 26.2 "seen, not changed").

A card whose step was already done another way (an Autopilot rule, HR on the normal screen, the person
moving on) is closed with the reason - status "closed", never "approved" - and nothing is applied."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agents.service import AgentError, decide, suggest
from app.audit.service import log_action
from app.hr_agents.autopilot import core, leftovers, people, runner
from app.hr_agents.autopilot.core import Run
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.intelligence import AgentSuggestion

from tests.test_agents_run_flow import _card, _fresh_cursor, _resignation
from tests.test_autopilot import _acts, _app, _tenant, allow, conf, db_session, user  # noqa: F401 -- shared fixtures


def _salary_card(db, app):
    return core.card(db, _tenant(), kind="agent_salary_decision", by_agent="salary", title="Salary counter for Meera",
                     payload={"application_id": str(app.id), "decision": "counter", "amount": 1200000},
                     permission="recruitment.salary.approve", entity_type="application", entity_id=app.id)


def test_card_still_waiting_is_left_alone(db_session, user, conf):
    app = _app(db_session, user, "salary_above_band")
    card = _salary_card(db_session, app)
    jd = suggest(db_session, _tenant(), agent="recruiter", kind="jd_draft", title="JD", payload={}, reviewer_permission="recruitment.job.edit")

    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 0
    db_session.refresh(card)
    db_session.refresh(jd)
    assert (card.status, jd.status) == ("pending", "pending")


def test_step_done_by_a_rule_closes_the_card_and_it_cannot_be_approved(db_session, user, allow, conf):
    app = _app(db_session, user, "salary_above_band")
    card = _salary_card(db_session, app)
    app.status = "salary_approved"  # the salary rule approved it after the card was made
    db_session.commit()
    log_action(db_session, "application", app.id, "salary_auto_decided", core.ACTOR, {"new_status": "salary_approved"})

    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and card.reviewed_by == core.ACTOR
    assert "salary approved" in card.closed_reason and "Autopilot rule" in card.closed_reason
    line = _acts(db_session, entity_id=app.id, action="close_card")
    assert len(line) == 1 and line[0].agent == "salary" and line[0].summary.startswith('Closed the card "Salary counter for Meera"')
    with pytest.raises(AgentError, match="closed"):
        decide(db_session, _tenant(), card, user=user, action="approve")
    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 0  # once


def test_step_done_by_hr_on_the_screen_is_named(db_session, user, conf):
    """Status unchanged (interview times keep the candidate in hr_selected) - the step's own done event closes it."""
    app = _app(db_session, user, "hr_selected")
    card = core.card(db_session, _tenant(), kind="agent_interview_send", by_agent="scheduling", title="Send interview times to Meera",
                     payload={"application_id": str(app.id)}, permission="recruitment.shortlisting.edit", entity_type="application", entity_id=app.id)
    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 0
    log_action(db_session, "application", app.id, "interview_scheduling_started", "hr@example.com", {"trigger": "send_now"})

    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and "already done by hr@example.com" in card.closed_reason


def test_assistant_shortlist_card_closes_only_when_no_candidate_is_waiting(db_session, user, conf):
    a = _app(db_session, user, "screened")
    cand = Candidate(full_name="Second Person", email=f"second-{uuid.uuid4().hex[:6]}@example.com")
    db_session.add(cand)
    db_session.commit()
    b = Application(job_role_id=a.job_role_id, candidate_id=cand.id, status="screened")
    db_session.add(b)
    db_session.commit()
    card = suggest(db_session, _tenant(), agent="recruiter", kind="agent_shortlist", title="Shortlist 2 (Screening agent)",
                   payload={"by_agent": "screening", "candidates": [{"application_id": str(a.id)}, {"application_id": str(b.id)}]},
                   reviewer_permission="recruitment.shortlisting.edit", entity_type="job_role", entity_id=None)
    a.status = "hr_selected"
    db_session.commit()
    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 0  # b still waits
    b.status = "hr_rejected"
    db_session.commit()

    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and "none of the candidates" in card.closed_reason


def test_resignation_approved_on_the_exits_screen_closes_the_card(db_session, user, conf, monkeypatch):
    monkeypatch.setattr("app.employees.self_service.needs_manager", lambda db, tenant, s: None)
    s = _resignation(db_session)
    people.resignations(db_session, _tenant(), Run("schedule"))
    card = _card(db_session, s.id, "agent_resignation_approve")
    s.status, s.approved_lwd = "approved", date.today() + timedelta(days=30)
    db_session.commit()

    assert leftovers.close_leftovers(db_session, _tenant(), Run("schedule")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and "already 'approved'" in card.closed_reason


def test_the_events_run_closes_the_card_right_after_the_rule_step(db_session, user, allow, conf):
    t = _tenant()
    _fresh_cursor(db_session, t)
    app = _app(db_session, user, "salary_above_band")
    card = _salary_card(db_session, app)
    app.status = "salary_approved"
    db_session.commit()
    log_action(db_session, "application", app.id, "salary_auto_decided", core.ACTOR, {"new_status": "salary_approved"})

    out = runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert out["cards_closed"] == 1
    db_session.refresh(card)
    assert card.status == "closed"


def test_closed_cards_leave_my_approvals(db_session, user, allow, conf):
    from app.agents.service import inbox

    app = _app(db_session, user, "salary_above_band")
    card = _salary_card(db_session, app)
    assert card.id in {c.id for c in inbox(db_session, _tenant(), user)}
    app.status = "salary_rejected"
    db_session.commit()
    leftovers.close_leftovers(db_session, _tenant(), Run("schedule"))
    assert card.id not in {c.id for c in inbox(db_session, _tenant(), user)}
    assert db_session.get(AgentSuggestion, card.id).final_payload_json is None  # nothing was applied
