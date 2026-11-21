"""Part 30.1: the Job agent (steps 1-2 of the flow).

A new job (job_role_created) wakes the Job agent: without a JD it drafts one with the AI (feature agents.job),
then raises a "Publish <title>" card with the JD, the publishing choices and the fields still missing. Approving
the card saves the JD (HR may edit it) and publishes through the SAME function as the Jobs screen. The agent never
publishes on its own; the card closes itself when the job is published or deleted by hand."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.audit.service import log_action
from app.hr_agents.autopilot import jobs as job_agent
from app.hr_agents.autopilot import leftovers, runner
from app.hr_agents.autopilot.core import Run
from app.models.intelligence import AgentSuggestion
from app.models.job_role import JobRole

from tests.test_autopilot import _acts, _tenant, allow, conf, db_session, user  # noqa: F401 -- shared fixtures

DRAFT = "Backend Engineer\n\nAbout the role\nBuild and run our APIs."


@pytest.fixture()
def job_on(conf):
    conf["autopilot.job.enabled"] = True
    return conf


@pytest.fixture()
def ai(monkeypatch):
    """AI allowed for the company; the model call is replaced (counts the calls)."""
    from app.platform.ai import governance

    calls = []

    def fake_complete(db, tenant, **kw):
        calls.append(kw)
        return SimpleNamespace(text=DRAFT, decision_log_id=None)

    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, feature: True)
    monkeypatch.setattr(governance, "governed_complete", fake_complete)
    return calls


def _job(db, user, *, jd=None, band=True, manager=True, pool=True, status="draft", **extra):
    from app.models.interviewer_pool import InterviewerPool

    job = JobRole(title=f"Backend Engineer {uuid.uuid4().hex[:4]}", department="Engineering", location="Chennai", status=status, jd_text=jd,
                  created_by=user.id, hiring_manager_id=user.id if manager else None,
                  salary_band_min=800000 if band else None, salary_band_max=1200000 if band else None,
                  technical_skills_must_have=["python"], **extra)
    db.add(job)
    db.commit()
    if pool:
        db.add(InterviewerPool(tenant_id=_tenant().tenant_id, name=f"Pool {job.title}", job_role_id=job.id, member_emails_json=["iv@example.com"]))
        db.commit()
    return job


def _card(db, job):
    return db.query(AgentSuggestion).filter(AgentSuggestion.entity_id == job.id, AgentSuggestion.kind == "agent_job_publish").one_or_none()


def _saved(db, job, action, at):
    """An audit row for the job at a chosen time (inside one test transaction now() never moves)."""
    from app.models.audit_log import AuditLog

    db.add(AuditLog(tenant_id=_tenant().tenant_id, entity_type="job_role", entity_id=job.id, action=action, actor="system", details={},
                    created_at=at))
    db.commit()


def _created(db, job, *, quiet_after=timedelta(minutes=11)):
    """The screen's create: the audit event the runner reads, a run a minute later (the job waits: HR may still be in
    the wizard), then a run once the job has not changed for the quiet time."""
    t = _tenant()
    start = datetime.now(timezone.utc)
    runner.run_events(db, t)  # first run sets the cursor
    _saved(db, job, "job_role_created", start)
    first = runner.run_events(db, t, now=start + timedelta(minutes=1))
    assert first.get("job_cards", 0) == 0 and _card(db, job) is None
    return runner.run_events(db, t, now=start + quiet_after)


# ---------------------------------------------------------------- the card


def test_new_job_without_jd_gets_a_drafted_jd_and_a_publish_card(db_session, user, job_on, ai):
    job = _job(db_session, user, pool=False, manager=False)
    out = _created(db_session, job)

    assert out["job_cards"] == 1 and len(ai) == 1 and ai[0]["feature"] == "agents.job"
    card = _card(db_session, job)
    assert card is not None and card.title.startswith(f"Publish {job.title}")
    p = card.payload_json
    assert p["by_agent"] == "autopilot.job" and p["job_id"] == str(job.id)
    assert p["jd_text"] == DRAFT and p["jd_drafted"] is True
    assert p["platforms"]["career_portal"] is True
    assert [(m["field"], m["blocking"]) for m in p["missing"]] == [("hiring_manager", True), ("interviewer_pool", True)]
    db_session.refresh(job)
    assert job.jd_text is None and job.status == "draft"  # nothing saved, nothing published: HR approves the card

    acts = _acts(db_session, entity_id=job.id, agent="job")
    assert [(a.action, a.outcome, a.entity_type) for a in acts] == [("propose_publish", "proposed", "job_role")]

    # the same event again: no second card, no second AI call
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    assert len(ai) == 1 and db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == job.id).count() == 1


def test_a_job_still_being_edited_in_the_wizard_waits_for_hr(db_session, user, job_on, ai):
    """Proof 30.1g: the wizard saves the job at step 1 with only the title; the agent drafted a JD from the title alone
    (one real AI call, "Not specified" everywhere) and raised a card while HR was still on step 2."""
    t = _tenant()
    job = _job(db_session, user, band=False, manager=False, pool=False)
    job.technical_skills_must_have = None
    db_session.commit()
    start = datetime.now(timezone.utc)
    runner.run_events(db_session, t)
    _saved(db_session, job, "job_role_created", start)
    runner.run_events(db_session, t, now=start + timedelta(minutes=1))
    # step 2..4 saved over the next minutes
    _saved(db_session, job, "job_role_updated", start + timedelta(minutes=4))
    job.technical_skills_must_have, job.salary_band_min, job.salary_band_max = ["python", "fastapi"], 900000, 1300000
    db_session.commit()
    _saved(db_session, job, "job_role_updated", start + timedelta(minutes=8))
    assert runner.run_events(db_session, t, now=start + timedelta(minutes=12))["job_cards"] == 0  # 4 min since the last save
    assert ai == [] and _card(db_session, job) is None and _acts(db_session, entity_id=job.id, agent="job") == []

    assert runner.run_events(db_session, t, now=start + timedelta(minutes=19))["job_cards"] == 1
    assert len(ai) == 1 and "fastapi" in ai[0]["messages"][0]["content"]  # drafted from the finished inputs
    assert [m["field"] for m in _card(db_session, job).payload_json["missing"]] == ["hiring_manager", "interviewer_pool"]
    assert runner.run_events(db_session, t, now=start + timedelta(minutes=30))["job_cards"] == 0  # once only


def test_a_job_published_from_the_wizard_never_gets_a_card(db_session, user, job_on, ai):
    from app.jobs.router import publish_job_platforms
    from app.schemas.job import PublishPlatformsRequest

    t = _tenant()
    job = _job(db_session, user, jd="JD")
    start = datetime.now(timezone.utc)
    runner.run_events(db_session, t)
    _saved(db_session, job, "job_role_created", start)
    runner.run_events(db_session, t, now=start + timedelta(minutes=1))
    publish_job_platforms(job.id, PublishPlatformsRequest(career_portal=True), db_session, user)
    assert runner.run_events(db_session, t, now=start + timedelta(minutes=20))["job_cards"] == 0
    assert _card(db_session, job) is None and ai == []
    assert core_state(db_session) == {}


def core_state(db):
    from app.hr_agents.autopilot.core import state_get

    return state_get(db, _tenant(), job_agent.WAITING, {})


def test_no_ai_for_the_company_gives_the_card_without_a_draft(db_session, user, job_on, monkeypatch):
    from app.platform.ai import governance

    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, feature: False)
    monkeypatch.setattr(governance, "governed_complete", lambda *a, **k: pytest.fail("the AI must not be called"))
    job = _job(db_session, user)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    assert card is not None and card.payload_json["jd_text"] in (None, "") and card.payload_json["jd_drafted"] is False
    assert card.payload_json["missing"] == []


def test_a_job_with_a_jd_only_gets_its_missing_fields_checked(db_session, user, job_on, ai):
    job = _job(db_session, user, jd="Our own JD", band=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    assert ai == [] and card.payload_json["jd_text"] == "Our own JD" and card.payload_json["jd_drafted"] is False
    assert [m["field"] for m in card.payload_json["missing"]] == ["salary_band"]


def test_a_job_already_published_on_create_gets_no_card(db_session, user, job_on, ai):
    job = _job(db_session, user, jd="JD", status="published")
    assert job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created")) is None
    assert _card(db_session, job) is None and ai == []


def test_agent_switched_off_does_nothing(db_session, user, job_on, ai):
    job_on["autopilot.job.enabled"] = False
    job = _job(db_session, user)
    _created(db_session, job)
    assert _card(db_session, job) is None and ai == [] and _acts(db_session, entity_id=job.id) == []


# ---------------------------------------------------------------- approving


def test_approve_publishes_through_the_jobs_screen_function(db_session, user, allow, job_on, ai, monkeypatch):
    from app.agents.service import decide
    from app.jobs import router as jobs_router

    calls = []
    real = jobs_router.publish_job_platforms

    def spy(job_id, payload, db, current_user):
        calls.append((job_id, payload.career_portal, current_user.email))
        return real(job_id, payload, db, current_user)

    monkeypatch.setattr(jobs_router, "publish_job_platforms", spy)
    job = _job(db_session, user)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)

    decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(job)
    assert calls == [(job.id, True, user.email)]
    assert job.status == "published" and job.jd_text == DRAFT and card.status == "approved"


def test_edited_jd_is_saved(db_session, user, allow, job_on, ai):
    from app.agents.service import decide

    job = _job(db_session, user)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    edited = {**card.payload_json, "jd_text": DRAFT + "\nHybrid: 3 days in the Chennai office."}
    decide(db_session, _tenant(), card, user=user, action="edit", edited_payload=edited)
    db_session.refresh(job)
    assert job.jd_text.endswith("3 days in the Chennai office.") and job.status == "published"


def test_missing_salary_band_refuses_and_the_card_stays_pending(db_session, user, allow, job_on, ai):
    from app.agents.service import AgentError, decide

    job = _job(db_session, user, band=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    with pytest.raises(AgentError, match="salary band"):
        decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.rollback()
    db_session.refresh(card)
    db_session.refresh(job)
    assert card.status == "pending" and job.status == "draft" and job.jd_text is None

    # filled on the screen afterwards -> the same card now publishes
    job.salary_band_min, job.salary_band_max = 900000, 1300000
    db_session.commit()
    decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(job)
    assert job.status == "published"


def test_no_hiring_manager_blocks_until_it_is_set(db_session, user, allow, job_on, ai):
    """Owner 2026-11-21: the wizard / job edit sets the hiring manager, so a missing one blocks the card again."""
    from app.agents.service import AgentError, decide

    job = _job(db_session, user, manager=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    assert card.payload_json["missing"] == [{"field": "hiring_manager", "label": "Hiring manager", "blocking": True}]
    with pytest.raises(AgentError, match="hiring manager"):
        decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.rollback()
    job.hiring_manager_id = user.id
    db_session.commit()
    decide(db_session, _tenant(), card, user=user, action="approve")
    db_session.refresh(job)
    assert job.status == "published"


def test_hiring_manager_falls_back_to_the_job_owner(db_session, user):
    from app.models.user import User

    job = _job(db_session, user, manager=False)
    assert job_agent.hiring_manager(db_session, _tenant(), job) == (user, True)
    manager = User(email=f"hm-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Hari", role="hiring_manager")
    db_session.add(manager)
    db_session.commit()
    job.hiring_manager_id = manager.id
    db_session.commit()
    assert job_agent.hiring_manager(db_session, _tenant(), job) == (manager, False)


def test_missing_interviewer_pool_blocks(db_session, user, allow, job_on, ai):
    from app.agents.service import AgentError, decide

    job = _job(db_session, user, pool=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    with pytest.raises(AgentError, match="interviewer pool"):
        decide(db_session, _tenant(), _card(db_session, job), user=user, action="approve")


def test_waiting_list_shows_what_is_still_missing_now(db_session, user, allow, job_on, ai):
    """Proof 30.1g: the card said "fill before publishing: interviewer pool" after HR had added the pool."""
    from app.hr_agents.autopilot_router import waiting
    from app.models.interviewer_pool import InterviewerPool

    job = _job(db_session, user, pool=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    item = lambda: next(i for i in waiting(db_session, user)["items"] if i["entity_id"] == str(job.id))  # noqa: E731
    assert [m["field"] for m in item()["payload"]["missing"]] == ["interviewer_pool"]
    db_session.add(InterviewerPool(tenant_id=_tenant().tenant_id, name=f"Pool {job.title}", job_role_id=job.id, member_emails_json=["iv@example.com"]))
    db_session.commit()
    assert item()["payload"]["missing"] == []


def test_a_card_without_any_jd_refuses(db_session, user, allow, job_on, monkeypatch):
    from app.agents.service import AgentError, decide
    from app.platform.ai import governance

    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, feature: False)
    job = _job(db_session, user)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    with pytest.raises(AgentError, match="JD"):
        decide(db_session, _tenant(), _card(db_session, job), user=user, action="approve")


# ---------------------------------------------------------------- closed by itself


def test_card_is_closed_when_the_job_is_published_by_hand(db_session, user, job_on, ai):
    from app.jobs.router import publish_job_platforms
    from app.schemas.job import PublishPlatformsRequest

    job = _job(db_session, user, jd="JD")
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    publish_job_platforms(job.id, PublishPlatformsRequest(career_portal=True), db_session, user)

    assert leftovers.close_leftovers(db_session, _tenant(), Run("event", "cards")) == 1
    card = _card(db_session, job)
    assert card.status == "closed" and "published" in card.closed_reason
    assert [a.agent for a in _acts(db_session, entity_id=job.id, action="close_card")] == ["job"]


def test_card_is_closed_when_the_job_is_deleted(db_session, user, job_on, ai):
    job = _job(db_session, user, pool=False)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    db_session.delete(job)
    db_session.commit()
    assert leftovers.close_leftovers(db_session, _tenant(), Run("event", "cards")) == 1
    db_session.refresh(card)
    assert card.status == "closed" and "no longer exists" in card.closed_reason


def test_deleting_the_job_on_the_screen_closes_its_card_within_the_minute(db_session, user, job_on, ai):
    """Proof 30.1g: job_role_deleted was not an event the per-minute run read, so the card waited for the hourly run."""
    from app.jobs.router import delete_job

    t = _tenant()
    job = _job(db_session, user, pool=False)
    job_agent.prepare_publish(db_session, t, job, Run("event", "job_role_created"))
    card = _card(db_session, job)
    start = datetime.now(timezone.utc)
    runner.run_events(db_session, t)
    delete_job(job.id, db_session, user)
    out = runner.run_events(db_session, t, now=start + timedelta(minutes=1))
    db_session.refresh(card)
    assert out["cards_closed"] == 1 and card.status == "closed" and "no longer exists" in card.closed_reason


def test_card_stays_while_the_job_is_still_a_draft(db_session, user, job_on, ai):
    job = _job(db_session, user)
    job_agent.prepare_publish(db_session, _tenant(), job, Run("event", "job_role_created"))
    assert leftovers.close_leftovers(db_session, _tenant(), Run("event", "cards")) == 0
    assert _card(db_session, job).status == "pending"


# ---------------------------------------------------------------- timeline


def test_job_events_go_on_the_job_timeline_and_the_journey(db_session, user, job_on):
    from app.hr_agents.autopilot_router import journey_job

    job = _job(db_session, user, jd="JD", status="published")
    t = _tenant()
    runner.run_events(db_session, t)
    log_action(db_session, "job_role", job.id, "job_platforms_published", "system", {"new_status": "published"})
    log_action(db_session, "job_role", job.id, "job_closed", user.email, {"reason": "filled"})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))

    acts = _acts(db_session, entity_id=job.id, agent="job")
    assert sorted(a.action for a in acts) == ["step_job_closed", "step_job_platforms_published"]
    assert all(a.outcome == "done" and a.entity_type == "job_role" and job.title in a.summary for a in acts)

    items = journey_job(job.id, db_session, user)["items"]
    assert [i["action"] for i in items] == ["step_job_platforms_published", "step_job_closed"]


def test_job_timeline_is_quiet_when_the_agent_is_off(db_session, user, job_on):
    job_on["autopilot.job.enabled"] = False
    job = _job(db_session, user, jd="JD", status="published")
    t = _tenant()
    runner.run_events(db_session, t)
    log_action(db_session, "job_role", job.id, "job_closed", user.email, {"reason": "filled"})
    runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert _acts(db_session, entity_id=job.id) == []
