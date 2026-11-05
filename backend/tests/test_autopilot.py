"""HR Autopilot (app/hr_agents/autopilot): automatic agents woken by audit-log events and schedules.

Settings are faked per test (`conf`), permissions granted by patching has_permission, and the AI
reading of BGV reports is replaced, so the real handlers, services and database rows run."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.audit.service import log_action
from app.hr_agents.autopilot import briefing, core, hiring, runner, watchdog
from app.hr_agents.autopilot.core import Run
from app.models.application import Application
from app.models.autopilot import AgentActivity
from app.models.candidate import Candidate
from app.models.comms import OutboundMessage
from app.models.intelligence import AgentSuggestion
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.tenancy.context import TENANT_1_ID, TenantContext


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


@pytest.fixture()
def db_session(_default_tenant_context):
    """Each commit is a SAVEPOINT, so a handler's rollback undoes only its own step (as in the app)."""
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
    u = User(email=f"auto-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name="Asha Rao", role="admin")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def allow(monkeypatch):
    import app.agents.service as agent_service
    import app.platform.iam.authz as authz

    monkeypatch.setattr(authz, "has_permission", lambda db, tenant, user, code: True)
    monkeypatch.setattr(agent_service, "has_permission", lambda db, tenant, user, code: True)


@pytest.fixture()
def conf(monkeypatch):
    """Autopilot settings for the test: on, every agent on, every rule off unless a test sets it."""
    values = {"autopilot.enabled": True, "autopilot.watchdog.stale_hours": 48, "autopilot.sourcing.min_strong": 3, "autopilot.briefing.hour": 9,
              "autopilot.briefing.email": False, "autopilot.rules.joining_dates_after_days": 14}
    for a in ("watchdog", "screening", "sourcing", "salary", "documents", "bgv", "offer", "onboarding", "exit", "briefing"):
        values[f"autopilot.{a}.enabled"] = True
    real = core.setting

    def fake(db, tenant, key):
        if key in values:
            return values[key]
        if key.startswith("autopilot.rules."):
            return 0
        return real(db, tenant, key)

    for mod in (core, watchdog, briefing, runner):
        monkeypatch.setattr(mod, "setting", fake)
    monkeypatch.setattr("app.platform.module_status.is_active", lambda db, tenant, key: True)
    return values


def _app(db_session, user, status, *, created_by=True, **extra):
    job = JobRole(title=f"Auto Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", created_by=user.id if created_by else None,
                  salary_band_min=800000, salary_band_max=1200000)
    db_session.add(job)
    db_session.commit()
    cand = Candidate(full_name=f"Meera {uuid.uuid4().hex[:4]}", email=f"meera-{uuid.uuid4().hex[:6]}@example.com", notice_period_days=extra.pop("notice", None))
    db_session.add(cand)
    db_session.commit()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status=status, **extra)
    db_session.add(app)
    db_session.commit()
    return app


def _acts(db_session, **f):
    q = db_session.query(AgentActivity)
    for k, v in f.items():
        q = q.filter(getattr(AgentActivity, k) == v)
    return q.all()


# ---------------------------------------------------------------- switches + events


def test_nothing_runs_while_autopilot_is_off(db_session, user, conf):
    conf["autopilot.enabled"] = False
    assert runner.run_events(db_session, _tenant()) == {"skipped": "autopilot off"}
    assert runner.run_hourly(db_session, _tenant()) == {"skipped": "autopilot off"}


def test_event_salary_inside_rule_is_decided_and_outside_is_a_card(db_session, user, allow, conf, monkeypatch):
    """salary_checked (audit log) -> Salary agent. 8% over band with a 10% rule: approved automatically.
    20% over: an approval card proposing a counter at the band maximum; nothing changes."""
    after = []
    monkeypatch.setattr("app.recruitment.joining_docs.after_salary_approved", lambda db, tenant, a, actor: after.append(a.id))
    conf["autopilot.rules.salary_max_over_band_pct"] = 10
    t = _tenant()
    first = runner.run_events(db_session, t)  # first run only sets the cursor (never replays history)
    assert "started" in first

    inside = _app(db_session, user, "salary_above_band", expected_salary=1300000, salary_check={"state": "needs_approval", "expected": 1300000, "band_max": 1200000})
    outside = _app(db_session, user, "salary_above_band", expected_salary=1440000, salary_check={"state": "flagged", "expected": 1440000, "band_max": 1200000})
    for a in (inside, outside):
        log_action(db_session, "application", a.id, "salary_checked", "system", {})

    out = runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert out["handled"] == 2
    db_session.refresh(inside)
    db_session.refresh(outside)
    assert inside.status == "salary_approved" and float(inside.approved_salary) == 1300000 and after == [inside.id]
    decided = _acts(db_session, entity_id=inside.id, outcome="decided")
    assert decided and decided[0].rule == "autopilot.rules.salary_max_over_band_pct" and decided[0].trigger == "event"
    assert outside.status == "salary_above_band"
    card = db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == outside.id).one()
    assert card.kind == "agent_salary_decision" and card.payload_json["decision"] == "counter" and float(card.payload_json["amount"]) == 1200000
    assert card.payload_json["by_agent"] == "autopilot.salary"

    again = runner.run_events(db_session, t, now=datetime.now(timezone.utc) + timedelta(minutes=2))
    assert again["events"] == 0  # the cursor moved on


def test_documents_clean_set_is_approved_by_rule_and_flagged_set_goes_to_hr(db_session, user, allow, conf, monkeypatch):
    from app.recruitment import joining_docs

    clean, flagged = _app(db_session, user, "salary_approved"), _app(db_session, user, "salary_approved")
    status = {clean.id: {"items": [{"label": "PAN card", "level": "green"}], "missing": [], "all_received": True, "all_approved": False, "reds": 0, "ambers": 0},
              flagged.id: {"items": [{"label": "PAN card", "level": "red"}], "missing": [], "all_received": True, "all_approved": False, "reds": 1, "ambers": 0}}
    approved = []
    monkeypatch.setattr(joining_docs, "status", lambda db, tenant, a: status[a.id])
    monkeypatch.setattr(joining_docs, "cross_check", lambda db, tenant, a: [])
    monkeypatch.setattr(joining_docs, "approve", lambda db, tenant, a, actor: approved.append((a.id, actor)) or {"approved": 1, "moved_to_bgv": True})
    conf["autopilot.rules.documents_auto_approve"] = True

    assert hiring.documents(db_session, _tenant(), clean, Run("event", "documents_submitted")) == "decided"
    assert hiring.documents(db_session, _tenant(), flagged, Run("event", "documents_submitted")) == "proposed"
    assert approved == [(clean.id, "autopilot")]
    card = db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == flagged.id).one()
    assert card.kind == "agent_documents_approve" and "PAN card: red" in card.payload_json["note"]


def test_clear_bgv_report_passes_by_rule_and_chains_to_the_offer_agent(db_session, user, allow, conf, monkeypatch):
    """BGV report received -> AI reads it as clear (95%) -> passed by rule -> Offer agent proposes joining dates (its rule is off)."""
    from app.bgv import vendors

    app = _app(db_session, user, "bgv_pending", notice=30)
    monkeypatch.setattr(vendors, "current", lambda db, application_id: type("A", (), {"status": "report_received", "id": uuid.uuid4()})())
    monkeypatch.setattr(hiring, "read_report", lambda db, tenant, a: {"verdict": "clear", "confidence": 0.95, "summary": "All checks verified.", "findings": []})
    monkeypatch.setattr("app.recruitment.joining_dates.after_bgv_passed", lambda *a, **k: None)
    conf["autopilot.rules.bgv_auto_pass_clear_report"] = True

    assert hiring.bgv_report(db_session, _tenant(), app, Run("event", "bgv_vendor_report_received")) == "decided"
    db_session.refresh(app)
    assert app.status == "bgv_cleared"
    card = db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == app.id, AgentSuggestion.kind == "agent_joining_dates").one()
    first = date.fromisoformat(card.payload_json["dates"][0])
    assert (first - date.today()).days >= 30  # the 30-day notice period wins over the 14-day lead time
    assert {a.action for a in _acts(db_session, entity_id=app.id)} >= {"read_report", "bgv_rule_pass", "propose_joining_dates"}


def test_unclear_bgv_report_is_never_decided(db_session, user, allow, conf, monkeypatch):
    from app.bgv import vendors

    app = _app(db_session, user, "bgv_pending")
    monkeypatch.setattr(vendors, "current", lambda db, application_id: type("A", (), {"status": "report_received", "id": uuid.uuid4()})())
    monkeypatch.setattr(hiring, "read_report", lambda db, tenant, a: {"verdict": "discrepancy", "confidence": 0.9, "summary": "Joining date differs by 2 months.", "findings": []})
    conf["autopilot.rules.bgv_auto_pass_clear_report"] = True
    assert hiring.bgv_report(db_session, _tenant(), app, Run("event", "bgv_vendor_report_received")) == "proposed"
    db_session.refresh(app)
    assert app.status == "bgv_pending"
    card = db_session.query(AgentSuggestion).filter(AgentSuggestion.entity_id == app.id).one()
    assert card.payload_json["decision"] == "discrepancy" and card.payload_json["note"] == "Joining date differs by 2 months."


@pytest.mark.parametrize("text, verdict, conf_", [
    ('{"verdict": "clear", "confidence": 0.97, "summary": "ok"}', "clear", 0.97),
    ('Here you go: {"verdict": "adverse", "confidence": "0.8"} thanks', "adverse", 0.8),
    ('{"verdict": "great", "confidence": 3}', "unclear", 1.0),
    ("not json at all", "unclear", 0.0),
])
def test_bgv_reader_output_is_parsed_defensively(text, verdict, conf_):
    v = hiring.parse_verdict(text)
    assert v["verdict"] == verdict and v["confidence"] == conf_


def test_joining_dates_are_three_working_days(db_session, user, conf):
    app = _app(db_session, user, "bgv_cleared")
    dates = [date.fromisoformat(d) for d in hiring.joining_dates_for(db_session, _tenant(), app, today=date(2026, 11, 6))]  # a Friday
    assert len(dates) == 3 and all(d.weekday() < 5 for d in dates) and dates == sorted(dates)
    assert (dates[0] - date(2026, 11, 6)).days >= 14


# ---------------------------------------------------------------- watchdog


def test_watchdog_escalates_once_a_day(db_session, user, allow, conf):
    app = _app(db_session, user, "salary_above_band")
    db_session.query(Application).filter(Application.id == app.id).update({"updated_at": datetime.now(timezone.utc) - timedelta(hours=72)})
    db_session.commit()
    t = _tenant()
    first = watchdog.run(db_session, t, Run())
    assert first["salary_waiting"] >= 1
    msgs = db_session.query(OutboundMessage).filter(OutboundMessage.related_entity_id == app.id, OutboundMessage.purpose == "agents.autopilot").all()
    assert len(msgs) >= 1 and "salary decision" in msgs[0].subject
    second = watchdog.run(db_session, t, Run())
    assert second["salary_waiting"] == 0  # quiet for 24 h per item
    assert len(_acts(db_session, entity_id=app.id, action="stale_salary")) == 1


def test_watchdog_resends_an_unsigned_offer_once_then_tells_the_recruiter(db_session, user, allow, conf, monkeypatch):
    from app.models.offer import Offer

    app = _app(db_session, user, "offer_sent")
    db_session.add(Offer(application_id=app.id, signed=False, sent_at=datetime.now(timezone.utc) - timedelta(days=4)))
    db_session.commit()
    resent = []
    monkeypatch.setattr("app.offers.revisions.resend", lambda db, tenant, offer, actor: resent.append(actor) or {})
    t = _tenant()
    watchdog.run(db_session, t, Run())
    assert resent == ["autopilot"]
    watchdog.run(db_session, t, Run())
    assert resent == ["autopilot"]  # not twice
    assert [a.outcome for a in _acts(db_session, entity_id=app.id)] == ["done", "escalated"] or \
        sorted(a.outcome for a in _acts(db_session, entity_id=app.id)) == ["done", "escalated"]


def test_one_failing_check_does_not_stop_the_others(db_session, user, allow, conf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("mailbox down")

    monkeypatch.setattr(watchdog, "CHECKS", (("broken", boom),) + tuple(c for c in watchdog.CHECKS if c[0] == "approvals_waiting"))
    out = watchdog.run(db_session, _tenant(), Run())
    assert out["broken"] == "failed" and "approvals_waiting" in out
    assert _acts(db_session, action="check_broken", outcome="failed")


# ---------------------------------------------------------------- briefing + page


def test_morning_briefing_once_per_person_per_day(db_session, user, allow, conf, monkeypatch):
    monkeypatch.setattr(briefing, "compose", lambda db, tenant, u, f: briefing.plain(f, "Asha"))
    t = _tenant()
    hour9 = datetime(2026, 11, 3, 3, 40, tzinfo=timezone.utc)  # 09:10 in Asia/Kolkata
    assert briefing.run(db_session, t, Run(), now=hour9 - timedelta(hours=2)) == 0  # not the briefing hour
    sent = briefing.run(db_session, t, Run(), now=hour9)
    assert sent >= 1
    row = [a for a in _acts(db_session, agent="briefing") if a.entity_id == user.id][0]
    assert row.details["text"].startswith("Good morning Asha")
    assert briefing.run(db_session, t, Run(), now=hour9 + timedelta(minutes=20)) == 0  # already sent today


def test_autopilot_page_api(client, db_session, conf, monkeypatch):
    import app.hr_agents.autopilot_router as r

    monkeypatch.setattr(r, "has_permission", lambda db, tenant, u, code: True)
    core.record(db_session, _tenant(), Run(), agent="watchdog", action="stale_salary", outcome="escalated", summary="Salary waiting - told HR.")
    ov = client.get("/api/v1/ui/autopilot/overview").json()
    assert ov["enabled"] is True and {a["key"] for a in ov["agents"]} >= {"watchdog", "briefing"} and "shortlist_min_score" in ov["rules"]
    items = client.get("/api/v1/ui/autopilot/activity?agent=watchdog").json()["items"]
    assert items and items[0]["summary"] == "Salary waiting - told HR."
    assert client.put("/api/v1/ui/autopilot/settings/ai.provider", json={"value": "x"}).status_code == 404  # only autopilot.* keys
    assert client.post("/api/v1/ui/autopilot/run/nothing").status_code == 404
