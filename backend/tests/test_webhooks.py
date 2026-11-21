"""Part 30.2d: webhooks -- events from the audit log and the cards, signed deliveries through generic_webhook, the
retry schedule, Resend, and what a payload may contain. The receiver is replaced (no network)."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.audit.service import log_action
from app.hr_agents.autopilot.core import state_set
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.public_api import WebhookDelivery
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.public_api import webhooks as hooks

from tests.conftest import _create_user

LIVE = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")
SANDBOX = TenantContext(tenant_id=TENANT_1_ID, slug="sandbox", isolation="dedicated_db")


@pytest.fixture()
def owner(db_session):
    return _create_user(db_session, role="admin", email=f"wh-{uuid.uuid4().hex[:6]}@example.com")


@pytest.fixture()
def receiver(monkeypatch):
    """Replaces the HTTP POST of the generic_webhook provider; `answers` is the status sequence to return."""
    import app.platform.connectors.providers.generic_webhook as gw

    state = {"calls": [], "answers": []}

    def fake_post(url, content, headers, timeout, follow_redirects=False):
        state["calls"].append({"url": url, "body": content, "headers": headers})
        code = state["answers"].pop(0) if state["answers"] else 200
        return httpx.Response(code, request=httpx.Request("POST", url))

    monkeypatch.setattr(gw.httpx, "post", fake_post)
    return state


def _application(db_session, owner, **extra):
    job = JobRole(title=f"WH Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", created_by=owner.id)
    db_session.add(job)
    db_session.commit()
    cand = Candidate(full_name="Asha Rao", email=f"asha-{uuid.uuid4().hex[:6]}@example.com")
    db_session.add(cand)
    db_session.commit()
    a = Application(job_role_id=job.id, candidate_id=cand.id, status="received", **extra)
    db_session.add(a)
    db_session.commit()
    return a


def _sub(db_session, owner, events, scopes=(), url="https://hooks.example.com/hr"):
    return hooks.create_subscription(db_session, LIVE, owner, url=url, events=list(events), scopes=list(scopes))


def _collect_after(db_session, start, log):
    """Cursor at `start`, the audit rows, then a run a minute later."""
    state_set(db_session, LIVE, hooks.CURSOR, {"at": (start - timedelta(seconds=1)).isoformat()})
    log()
    return hooks.collect(db_session, LIVE, now=datetime.now(timezone.utc) + timedelta(minutes=1))


def _deliveries(db_session, sub):
    return db_session.query(WebhookDelivery).filter(WebhookDelivery.subscription_id == sub.id).order_by(WebhookDelivery.created_at).all()


def test_signature_verifies_with_the_secret_shown_once(db_session, owner, receiver):
    sub, secret = _sub(db_session, owner, ["application.created"])
    assert secret.startswith("whsec_") and secret not in sub.secret_enc  # stored encrypted
    a = _application(db_session, owner)
    assert _collect_after(db_session, datetime.now(timezone.utc), lambda: log_action(db_session, "application", a.id, "application_created", "system", {})) == 1
    out = hooks.send_due(db_session, LIVE)
    assert out["delivered"] == 1
    call = receiver["calls"][0]
    expected = hmac.new(secret.encode(), call["body"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(call["headers"]["X-Signature"], expected)
    d = _deliveries(db_session, sub)[0]
    assert call["headers"]["X-Event"] == "application.created" and call["headers"]["X-Delivery-Id"] == str(d.id)
    body = json.loads(call["body"])
    assert body["event"] == "application.created" and body["id"] == str(d.id) and body["data"]["application_id"] == str(a.id)
    assert d.status == "delivered" and d.attempts == 1 and d.last_status == 200


def test_retry_schedule_then_failed_then_resend(db_session, owner, receiver):
    sub, _ = _sub(db_session, owner, ["application.created"])
    a = _application(db_session, owner)
    _collect_after(db_session, datetime.now(timezone.utc), lambda: log_action(db_session, "application", a.id, "application_created", "system", {}))
    d = _deliveries(db_session, sub)[0]
    receiver["answers"] = [500] * 6
    t = datetime.now(timezone.utc)
    gaps = []
    for _ in range(6):
        hooks.attempt(db_session, d, sub, now=t)
        if d.next_at:
            gaps.append(d.next_at - t)
            t = d.next_at
    assert gaps == [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=12)]
    assert d.status == "failed" and d.attempts == 6 and d.last_status == 500 and "500" in d.last_error

    hooks.resend(db_session, d)
    assert d.status == "pending" and d.attempts == 0
    assert hooks.send_due(db_session, LIVE)["delivered"] == 1 and d.status == "delivered"


def test_salary_figures_only_for_a_sensitive_subscription(db_session, owner, receiver):
    plain, _ = _sub(db_session, owner, ["salary.decided"])
    sens, _ = _sub(db_session, owner, ["salary.decided"], scopes=["sensitive"])
    a = _application(db_session, owner, approved_salary=1500000)
    _collect_after(db_session, datetime.now(timezone.utc),
                   lambda: log_action(db_session, "application", a.id, "salary_approval_decision", "hr@example.com", {"decision": "approve"}))
    p_plain, p_sens = _deliveries(db_session, plain)[0].payload["data"], _deliveries(db_session, sens)[0].payload["data"]
    assert "salary" not in p_plain and p_plain["decision"] == "approve"
    assert p_sens["salary"] == {"approved_salary": 1500000.0}
    assert "resume" not in json.dumps(p_sens).lower()


def test_events_are_mapped_and_filtered(db_session, owner, receiver):
    sub, _ = _sub(db_session, owner, ["job.published", "salary.decided", "application.screened"])
    a = _application(db_session, owner)
    job = db_session.get(JobRole, a.job_role_id)

    def log():
        log_action(db_session, "job_role", job.id, "job_platforms_published", "system", {"new_status": "ready_for_publishing"})  # boards only: no
        log_action(db_session, "job_role", job.id, "job_platforms_published", "system", {"new_status": "published", "published_platforms": {"career_portal": True}})
        log_action(db_session, "application", a.id, "salary_auto_decided", "autopilot", {"new_status": "salary_above_band"})  # routed to HR: no
        log_action(db_session, "application", a.id, "application_created", "system", {})  # not subscribed

    assert _collect_after(db_session, datetime.now(timezone.utc), log) == 1
    d = _deliveries(db_session, sub)[0]
    assert d.event == "job.published" and d.payload["data"]["platforms"] == {"career_portal": True}


def test_card_events(db_session, owner, receiver):
    from app.agents.service import decide, suggest

    sub, _ = _sub(db_session, owner, ["card.created", "card.decided"])
    a = _application(db_session, owner)
    start = datetime.now(timezone.utc)
    state_set(db_session, LIVE, hooks.CURSOR, {"at": (start - timedelta(seconds=1)).isoformat()})
    card = suggest(db_session, LIVE, agent="recruiter", kind="jd_draft", title="JD for X (Autopilot: job)", payload={"jd_text": "x"},
                   reviewer_permission="recruitment.job.edit", entity_type="application", entity_id=a.id, reviewer_user_id=owner.id)
    decide(db_session, LIVE, card, user=owner, action="reject")
    hooks.collect(db_session, LIVE, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    got = {d.event: d.payload["data"] for d in _deliveries(db_session, sub)}
    assert set(got) == {"card.created", "card.decided"}
    assert got["card.created"]["title"] == "JD for X" and got["card.decided"]["status"] == "rejected" and got["card.decided"]["decided_by"] == owner.email


def test_first_run_never_replays_history(db_session, owner, receiver):
    from app.models.autopilot import AutopilotState

    db_session.query(AutopilotState).filter(AutopilotState.key == hooks.CURSOR).delete()  # a company that never had webhooks
    db_session.commit()
    sub, _ = _sub(db_session, owner, ["application.created"])
    a = _application(db_session, owner)
    log_action(db_session, "application", a.id, "application_created", "system", {})
    assert hooks.collect(db_session, LIVE, now=datetime.now(timezone.utc) + timedelta(minutes=1)) == 0  # no cursor yet: starts now
    assert _deliveries(db_session, sub) == []


@pytest.mark.parametrize("url, tenant, ok", [
    ("https://hooks.example.com/x", LIVE, True),
    ("http://hooks.example.com/x", LIVE, False),
    ("https://127.0.0.1/x", LIVE, False),
    ("https://10.0.0.5/x", LIVE, False),
    ("http://localhost:9000/hook", LIVE, False),
    ("http://localhost:9000/hook", SANDBOX, True),
    ("http://127.0.0.1:9000/hook", SANDBOX, True),
])
def test_webhook_urls(url, tenant, ok):
    if ok:
        assert hooks.check_url(url, tenant)
    else:
        with pytest.raises(ValueError):
            hooks.check_url(url, tenant)


def test_unknown_events_and_scopes_are_refused(db_session, owner):
    with pytest.raises(ValueError, match="Unknown"):
        _sub(db_session, owner, ["application.created", "everything"])
    with pytest.raises(ValueError, match="sensitive"):
        _sub(db_session, owner, ["application.created"], scopes=["admin"])


def test_developers_page_api(client, db_session, receiver, monkeypatch):
    import app.platform.iam.authz as authz

    monkeypatch.setattr(authz, "has_permission", lambda db, tenant, user, code: True)
    created = client.post("/api/v1/ui/developers/keys", json={"name": "ATS", "scopes": ["jobs", "cards"]})
    assert created.status_code == 201 and created.json()["key"].startswith("hra_")
    listed = client.get("/api/v1/ui/developers/keys").json()["items"]
    assert any(k["id"] == created.json()["id"] for k in listed) and all("key" not in k for k in listed)  # shown once
    assert client.post(f"/api/v1/ui/developers/keys/{created.json()['id']}/revoke").json()["revoked_at"]

    hook = client.post("/api/v1/ui/developers/webhooks", json={"url": "https://hooks.example.com/hr", "events": ["offer.signed"]})
    assert hook.status_code == 201 and hook.json()["secret"].startswith("whsec_")
    assert "secret" not in client.get("/api/v1/ui/developers/webhooks").json()["items"][0]
    ping = client.post(f"/api/v1/ui/developers/webhooks/{hook.json()['id']}/ping").json()
    assert ping["event"] == "ping" and ping["status"] == "delivered"
    log = client.get(f"/api/v1/ui/developers/webhooks/{hook.json()['id']}/deliveries").json()["items"]
    assert log[0]["id"] == ping["id"]
    assert client.post("/api/v1/ui/developers/webhooks", json={"url": "http://x.example.com", "events": ["offer.signed"]}).status_code == 400


def test_developers_page_is_admin_only(client, db_session, make_auth_headers):
    h = make_auth_headers(role="recruiter")
    assert client.get("/api/v1/ui/developers/keys", headers=h).status_code == 403
