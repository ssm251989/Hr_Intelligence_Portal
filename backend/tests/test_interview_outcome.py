"""Part 30.3: the interview-outcome card. Interviewers send scorecards (ratings, notes, a recommendation); once the whole
round is in, the Scheduling agent summarises them (AI replaced here) and raises "Interview result for <name>: ..." for
the job's hiring manager (fallback: the job owner). Approving applies the hiring manager's pick through the feedback
screen's own decision code; a decision on the screen closes the card; the watchdog chases missing scorecards."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.audit.service import log_action
from app.hr_agents.autopilot import interviews as outcome
from app.hr_agents.autopilot import leftovers, runner
from app.hr_agents.autopilot.core import Run
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.intelligence import AgentSuggestion
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User

from tests.test_autopilot import _acts, _tenant, allow, conf, db_session, user  # noqa: F401 -- shared fixtures

SUMMARY = {"one_line": "Strong backend skills, weaker on system design", "strengths": ["Python depth"], "concerns": ["System design"],
           "disagreements": ["Interviewer 2 wants another round"], "suggested_next_step": "move_forward", "why": "Two of three recommend it."}


@pytest.fixture()
def ai(monkeypatch):
    from app.platform.ai import governance

    calls = []
    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, f: True)
    monkeypatch.setattr(governance, "governed_json", lambda db, tenant, **kw: calls.append(kw) or (SUMMARY, None))
    return calls


@pytest.fixture()
def manager(db_session):
    u = User(email=f"hm-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Hari Manager", role="hiring_manager")
    db_session.add(u)
    db_session.commit()
    return u


def _setup(db_session, owner, manager=None, *, panel=2):
    job = JobRole(title=f"Panel Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", created_by=owner.id,
                  hiring_manager_id=getattr(manager, "id", None), salary_band_min=800000, salary_band_max=1200000)
    db_session.add(job)
    db_session.commit()
    cand = Candidate(full_name="Meera Iyer", email=f"meera-{uuid.uuid4().hex[:6]}@example.com")
    db_session.add(cand)
    db_session.commit()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status="interview_scheduled")
    db_session.add(app)
    db_session.commit()
    ivs = []
    for n in range(panel):
        iv = Interview(application_id=app.id, interviewer_name=("Ravi Kumar", "Priya Nair", "Arun Das")[n], interviewer_email=f"iv{n + 1}-{uuid.uuid4().hex[:4]}@example.com",
                       scheduled_at=datetime.now(timezone.utc) - timedelta(hours=2))
        db_session.add(iv)
        ivs.append(iv)
    db_session.commit()
    return app, ivs


def _score(db_session, iv, overall, rec, note="ok"):
    iv.technical_rating, iv.communication_rating, iv.overall_rating, iv.recommendation, iv.comments = overall, overall, overall, rec, note
    db_session.commit()


def _card(db_session, app):
    return db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == app.id, AgentSuggestion.kind == outcome.KIND).order_by(
        AgentSuggestion.created_at.desc()).first()


# ---------------------------------------------------------------- the card


def test_card_comes_after_the_last_scorecard_for_the_hiring_manager(db_session, user, manager, conf, ai):
    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 4, "selected")
    assert outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x")) is None and ai == []  # still waiting for b

    _score(db_session, b, 3, "another_round")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    assert card.title.startswith("Interview result for Meera Iyer: Strong backend skills")
    assert card.reviewer_user_id == manager.id and card.payload_json["hiring_manager_is_job_owner"] is False
    p = card.payload_json
    assert p["summary"]["concerns"] == ["System design"] and [c["recommendation"] for c in p["scorecards"]] == ["selected", "another_round"]
    assert p["decision"] is None  # 1 - 1: a tie has no default
    prompt = ai[0]["messages"][0]["content"]
    assert ai[0]["feature"] == "agents.interview_summary" and "Interviewer 1:" in prompt
    assert "Meera" not in prompt and "Ravi" not in prompt and "Priya" not in prompt  # names never sent to the AI
    assert [x.action for x in _acts(db_session, entity_id=app.id, agent="scheduling")] == ["propose_interview_outcome"]
    assert outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x")) is None  # one card per round


def test_majority_is_the_default_and_a_tie_has_none():
    assert outcome.majority(["selected", "selected", "rejected"]) == "move_forward"
    assert outcome.majority(["rejected", "another_round", "rejected"]) == "reject"
    assert outcome.majority(["selected", "rejected"]) is None
    assert outcome.majority([None, None]) is None


def test_without_a_hiring_manager_the_job_owner_gets_it(db_session, user, conf, ai):
    app, ivs = _setup(db_session, user, None, panel=1)
    _score(db_session, ivs[0], 5, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    assert card.reviewer_user_id == user.id and card.payload_json["hiring_manager_is_job_owner"] is True and card.payload_json["decision"] == "move_forward"


def test_no_ai_gives_the_card_with_scores_only(db_session, user, manager, conf, monkeypatch):
    from app.platform.ai import governance

    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, f: False)
    monkeypatch.setattr(governance, "governed_json", lambda *a, **k: pytest.fail("the AI must not be called"))
    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 4, "selected")
    _score(db_session, b, 5, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    assert card.payload_json["summary"] is None and "AI is not switched on" in card.payload_json["note"]
    assert card.title == "Interview result for Meera Iyer: overall 4.5/5; 2 selected (Autopilot: scheduling)"


def test_the_runner_raises_it_from_the_scorecard_event(db_session, user, manager, conf, ai):
    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 4, "selected")
    _score(db_session, b, 4, "selected")
    start = datetime.now(timezone.utc)
    runner.run_events(db_session, _tenant())
    log_action(db_session, "interview", b.id, "interview_feedback_recorded", "system", {"overall_rating": 4, "decision": None})
    out = runner.run_events(db_session, _tenant(), now=start + timedelta(minutes=1))
    assert out["handled"] == 1 and _card(db_session, app) is not None


# ---------------------------------------------------------------- deciding


def test_move_forward_is_the_same_as_the_screens_decision(db_session, user, manager, conf, ai, allow, client, monkeypatch):
    """The card and the feedback screen end in the same state, with the same follow-on (salary stage)."""
    from app.agents.service import decide
    from app.recruitment import salary_auto

    follow = []
    monkeypatch.setattr(salary_auto, "after_interview", lambda db, t, application, iv, actor: follow.append(application.id))
    monkeypatch.setattr(salary_auto, "check", lambda db, t, application, actor: None)
    from app.platform import module_status

    monkeypatch.setattr(module_status, "active_modules", lambda db, t: {"salary", "interviews", "bgv"})

    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 4, "selected")
    _score(db_session, b, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    decide(db_session, _tenant(), card, user=manager, action="approve")
    db_session.refresh(app)

    screen_app, (s1,) = _setup(db_session, user, manager, panel=1)
    r = client.patch(f"/interviews/{s1.id}/feedback", json={"overall_rating": 4, "comments": "ok", "decision": "selected"})
    assert r.status_code == 200, r.text
    db_session.refresh(screen_app)
    assert app.status == screen_app.status == "interview_selected"
    assert follow == [app.id, screen_app.id] and card.status == "approved"


def test_reject_needs_a_reason_and_no_default_needs_a_pick(db_session, user, manager, conf, ai, allow):
    from app.agents.service import AgentError, decide

    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 2, "rejected")
    _score(db_session, b, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    with pytest.raises(AgentError, match="Pick the result"):
        decide(db_session, _tenant(), card, user=manager, action="approve")  # a tie: no default
    with pytest.raises(AgentError, match="reason"):
        decide(db_session, _tenant(), card, user=manager, action="edit", edited_payload={**card.payload_json, "decision": "reject"})
    db_session.rollback()
    decide(db_session, _tenant(), card, user=manager, action="edit",
           edited_payload={**card.payload_json, "decision": "reject", "reason": "System design is below what the role needs."})
    db_session.refresh(app)
    assert app.status == "interview_rejected" and card.status == "edited"


def test_another_round_keeps_the_candidate_and_the_next_round_gets_its_own_card(db_session, user, manager, conf, ai, allow):
    from app.agents.service import decide

    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 3, "another_round")
    _score(db_session, b, 3, "another_round")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    decide(db_session, _tenant(), card, user=manager, action="approve")
    db_session.refresh(app)
    db_session.refresh(card)
    assert app.status == "interview_scheduled" and card.status == "approved"
    assert (card.final_payload_json or {}).get("result", {}).get("next") == "another round"

    c = Interview(application_id=app.id, interviewer_name="Round 2", interviewer_email="r2@example.com", scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1))
    db_session.add(c)
    db_session.commit()
    assert outcome.round_interviews(db_session, _tenant(), app) == [c]
    _score(db_session, c, 5, "selected")
    second = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    assert second.id != card.id and second.payload_json["interview_ids"] == [str(c.id)]


def test_card_closes_when_the_decision_is_made_on_the_screen(db_session, user, manager, conf, ai, client):
    app, (a, b) = _setup(db_session, user, manager)
    _score(db_session, a, 4, "selected")
    _score(db_session, b, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    r = client.patch(f"/interviews/{b.id}/feedback", json={"decision": "selected"})
    assert r.status_code == 200, r.text
    assert leftovers.close_leftovers(db_session, _tenant(), Run("event", "cards")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and "moved on" in card.closed_reason


# ---------------------------------------------------------------- watchdog


def test_missing_scorecard_is_nudged_once_then_the_hiring_manager_is_told(db_session, user, manager, conf, monkeypatch):
    import app.platform.comms.defaults as defaults
    from app.models.comms import OutboundMessage

    sent = []
    monkeypatch.setattr(defaults, "send_default", lambda db, t, key, **kw: sent.append((key, kw["to"])))
    app, (a, b) = _setup(db_session, user, manager)
    for iv in (a, b):
        iv.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=30)
    db_session.commit()
    _score(db_session, a, 4, "selected")
    now = datetime.now(timezone.utc)

    assert outcome.missing_scorecards(db_session, _tenant(), Run(), now) == 1
    assert sent == [("recruitment.interview_feedback_reminder", [b.interviewer_email])]
    assert outcome.missing_scorecards(db_session, _tenant(), Run(), now + timedelta(hours=2)) == 0  # once only, HM not yet
    assert outcome.missing_scorecards(db_session, _tenant(), Run(), now + timedelta(hours=25)) == 1  # 24 h after the reminder
    told = [m for m in db_session.query(OutboundMessage).filter(OutboundMessage.related_entity_id == app.id).all() if manager.email in (m.to_addresses or [])]
    assert len(told) == 1 and "even after a reminder" in told[0].subject
    assert outcome.missing_scorecards(db_session, _tenant(), Run(), now + timedelta(hours=60)) == 0 and len(sent) == 1


def test_only_the_named_hiring_manager_decides_and_my_approvals_sends_them_to_the_picker(db_session, user, manager, conf, ai):
    from app.agents.service import decide
    from app.experience.inbox import items_for
    from app.platform.iam.roles import bridge_single_user

    app, (a,) = _setup(db_session, user, manager, panel=1)
    _score(db_session, a, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    other = User(email=f"hm2-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Other HM", role="hiring_manager")
    db_session.add(other)
    db_session.commit()
    bridge_single_user(db_session, _tenant(), other)
    with pytest.raises(PermissionError):
        decide(db_session, _tenant(), card, user=other, action="approve")  # another job's hiring manager
    bridge_single_user(db_session, _tenant(), manager)
    items = [i for i in items_for(db_session, _tenant(), manager) if i["id"] == str(card.id)]
    assert items and items[0]["path"] == "/autopilot" and items[0]["subtitle"] == "pick the interview result"


def test_the_named_hiring_manager_can_decide_through_the_screen_endpoint(db_session, user, manager, conf, ai, anonymous_client):
    """Proof 30.3f: the hiring manager saw the card but approving answered "Missing permission: agents.suggestion.view"."""
    from app.core.security import create_access_token
    from app.platform.iam.roles import bridge_single_user

    bridge_single_user(db_session, _tenant(), manager)
    app, (a,) = _setup(db_session, user, manager, panel=1)
    a.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    _score(db_session, a, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    other = User(email=f"hm3-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Other", role="hiring_manager")
    db_session.add(other)
    db_session.commit()
    bridge_single_user(db_session, _tenant(), other)

    url = f"/api/v1/intelligence/agents/suggestions/{card.id}/decision"
    r = anonymous_client.post(url, json={"action": "approve"}, headers={"Authorization": f"Bearer {create_access_token(str(other.id))}"})
    assert r.status_code == 403
    r = anonymous_client.post(url, json={"action": "approve"}, headers={"Authorization": f"Bearer {create_access_token(str(manager.id))}"})
    assert r.status_code == 200, r.text
    db_session.refresh(app)
    assert r.json()["status"] == "approved" and app.status == "interview_selected"



def test_interviewers_booked_on_the_screen_are_named_on_the_card(db_session, user, manager, conf, ai):
    """Proof 30.3f: the recruiter's booking keeps only interviewer_id, and the card showed "Interviewer 1 / 2"."""
    iv_user = User(email=f"ivu-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Kavya Iyer", role="interviewer")
    db_session.add(iv_user)
    db_session.commit()
    app, (a,) = _setup(db_session, user, manager, panel=1)
    a.interviewer_name, a.interviewer_email, a.interviewer_id = None, None, iv_user.id
    db_session.commit()
    _score(db_session, a, 4, "selected")
    card = outcome.prepare_outcome(db_session, _tenant(), app, Run("event", "x"))
    assert card.payload_json["scorecards"][0]["interviewer"] == "Kavya Iyer" and "Kavya" not in ai[0]["messages"][0]["content"]
