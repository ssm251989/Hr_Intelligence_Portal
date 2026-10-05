"""Fix 2026-10-05: joiner actions by stage -- withdraw only before joining, exits only after."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.core_hr import Employee
from app.models.intelligence import AgentSuggestion
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.service_desk import Separation
from app.onboarding import joiner_actions, joiner_stage
from app.onboarding.joiner_stage import ActionNotAllowed
from app.onboarding.portal import PreboardingPortal
from app.platform.tenancy.context import get_current_tenant


def _joiner(db_session, *, days_to_join=10, email="joiner@example.com"):
    job = JobRole(title="Junior AI Developer", department="AI", positions_count=1, status="published")
    db_session.add(job)
    db_session.flush()
    cand = Candidate(full_name="Ravi Teja", email=email, first_name="Ravi Teja", last_name="K")
    db_session.add(cand)
    db_session.flush()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status="onboarding_started", approved_salary=300000)
    db_session.add(app)
    db_session.flush()
    offer = Offer(application_id=app.id, signed=True, signed_at=datetime.now(timezone.utc), joining_date=date.today() + timedelta(days=days_to_join))
    db_session.add(offer)
    db_session.commit()
    case = PreboardingPortal(db_session, get_current_tenant()).create_case_from_offer(offer.id)
    return job, app, offer, case


def test_before_joining_only_withdraw_or_decline(db_session):
    job, app, _offer, case = _joiner(db_session)
    assert joiner_stage.stage(db_session, case) == "before_joining"
    assert joiner_stage.allowed_actions(db_session, case) == ["withdraw_offer", "candidate_declined"]
    for action in ("mark_joined", "no_show", "absconded", "resigned"):
        with pytest.raises(ActionNotAllowed):
            joiner_stage.require(db_session, case, action, name="Ravi")
    out = joiner_actions.withdraw_offer(db_session, get_current_tenant(), case, actor="hr@example.com", reason="Role put on hold")
    assert case.status == "revoked" and db_session.get(Application, app.id).status == "offer_withdrawn"
    assert out["budget"] == "released" and out["cancelled"]["portal_link"] == "revoked"
    todo = db_session.query(AgentSuggestion).filter(AgentSuggestion.kind == "position_open_again", AgentSuggestion.entity_id == job.id).one()
    assert todo.title.startswith("Position open again")
    with pytest.raises(ActionNotAllowed, match="already closed"):
        joiner_actions.withdraw_offer(db_session, get_current_tenant(), case, actor="hr", reason="again")


def test_joined_person_cannot_be_withdrawn_but_can_exit(db_session):
    _job, app, _offer, case = _joiner(db_session, days_to_join=-3)
    assert joiner_stage.stage(db_session, case) == "joining_due"
    joiner_actions.mark_joined(db_session, get_current_tenant(), case, actor="hr@example.com")
    assert case.status == "joined" and db_session.get(Application, app.id).status == "onboarding_completed"
    assert joiner_stage.allowed_actions(db_session, case) == ["not_reporting", "absconded", "resigned", "terminated"]
    with pytest.raises(ActionNotAllowed, match="already joined"):
        joiner_actions.withdraw_offer(db_session, get_current_tenant(), case, actor="hr", reason="changed our mind")
    with pytest.raises(ActionNotAllowed):
        joiner_actions.candidate_declined(db_session, get_current_tenant(), case, actor="hr", reason_code="personal")
    out = joiner_actions.record_exit(db_session, get_current_tenant(), case, kind="resigned", actor="hr@example.com",
                                     last_working_day=date.today(), reason_code="better_offer", notes="Left for a startup")
    sep = db_session.get(Separation, out["separation_id"])
    assert sep.separation_type == "resignation" and sep.status == "clearance" and sep.rehire_eligible is True
    assert case.status == "exited" and db_session.get(Application, app.id).status == "left_after_joining"
    assert db_session.get(Employee, case.employee_id).status == "on_notice"  # record kept; the exit case completes it
    assert joiner_stage.allowed_actions(db_session, case) == []


def test_not_reporting_notices_then_absconded(db_session):
    _job, app, _offer, case = _joiner(db_session, days_to_join=-20)
    joiner_actions.mark_joined(db_session, get_current_tenant(), case, actor="hr")
    last = date.today() - timedelta(days=1)
    joiner_actions.start_not_reporting(db_session, get_current_tenant(), case, actor="hr", last_seen=last)
    assert "stop_not_reporting" in joiner_stage.allowed_actions(db_session, case)
    t = get_current_tenant()
    assert joiner_actions.run_not_reporting_notices(db_session, t, today=last + timedelta(days=1)) == 0
    assert joiner_actions.run_not_reporting_notices(db_session, t, today=last + timedelta(days=2)) == 1   # reminder
    assert joiner_actions.run_not_reporting_notices(db_session, t, today=last + timedelta(days=2)) == 0   # once only
    assert joiner_actions.run_not_reporting_notices(db_session, t, today=last + timedelta(days=10)) == 2  # show-cause + final
    kinds = [n["kind"] for n in case.attributes_json["not_reporting"]["notices"]]
    assert kinds == ["reminder", "show_cause", "final"]
    out = joiner_actions.record_exit(db_session, t, case, kind="absconded", actor="hr", last_working_day=last, reason_code="no_contact",
                                     notes="No reply to 3 notices")
    sep = db_session.get(Separation, out["separation_id"])
    assert sep.separation_type == "absconding" and sep.rehire_eligible is False and len(sep.absconding_notices_json) == 3
    assert case.attributes_json["not_reporting"]["status"] == "confirmed"


def test_stop_not_reporting_when_they_return(db_session):
    _job, _app, _offer, case = _joiner(db_session, days_to_join=-5)
    joiner_actions.mark_joined(db_session, get_current_tenant(), case, actor="hr")
    joiner_actions.start_not_reporting(db_session, get_current_tenant(), case, actor="hr", last_seen=date.today())
    joiner_actions.stop_not_reporting(db_session, get_current_tenant(), case, actor="hr", note="Was unwell, back today")
    assert case.attributes_json["not_reporting"]["status"] == "stopped"
    assert joiner_actions.run_not_reporting_notices(db_session, get_current_tenant(), today=date.today() + timedelta(days=30)) == 0


def test_no_show_and_report(db_session):
    _job, app, _offer, case = _joiner(db_session, days_to_join=0)
    joiner_actions.no_show(db_session, get_current_tenant(), case, actor="hr", reason_code="no_contact", contacted_on=date.today())
    assert case.status == "no_show" and db_session.get(Application, app.id).status == "no_show"
    rep = joiner_actions.dropout_report(db_session, get_current_tenant())
    assert rep["totals"]["no_show"] >= 1
    assert any(r["key"] == "Could not be reached" for r in rep["by_reason"])


def test_withdraw_refused_by_api_after_joining(client, db_session):
    _job, _app, _offer, case = _joiner(db_session, days_to_join=-1)
    joiner_actions.mark_joined(db_session, get_current_tenant(), case, actor="hr")
    r = client.post(f"/api/v1/onboarding/cases/{case.id}/revoke", json={"reason": "test"})
    assert r.status_code == 409
    assert "already joined" in r.json()["detail"]["message"]


def test_one_open_todo_per_job(db_session):
    job, _app, _offer, case = _joiner(db_session, email="a@example.com")
    joiner_actions.withdraw_offer(db_session, get_current_tenant(), case, actor="hr", reason="Budget frozen")
    cand = Candidate(full_name="Second Person", email="b@example.com", first_name="Second")
    db_session.add(cand)
    db_session.flush()
    app2 = Application(job_role_id=job.id, candidate_id=cand.id, status="onboarding_started")
    db_session.add(app2)
    db_session.flush()
    offer2 = Offer(application_id=app2.id, signed=True, joining_date=date.today() + timedelta(days=5))
    db_session.add(offer2)
    db_session.commit()
    case2 = PreboardingPortal(db_session, get_current_tenant()).create_case_from_offer(offer2.id)
    joiner_actions.candidate_declined(db_session, get_current_tenant(), case2, actor="hr", reason_code="compensation")
    todos = db_session.query(AgentSuggestion).filter(AgentSuggestion.kind == "position_open_again", AgentSuggestion.entity_id == job.id).all()
    assert len(todos) == 1 and len(todos[0].payload_json["people"]) == 2
