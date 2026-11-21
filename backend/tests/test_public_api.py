"""Part 30.2: the public API (/api/public/v1). Keys, scopes, errors, limits, idempotency, and each endpoint against
the screen function it calls. The AI is replaced where an endpoint would call it; everything else is real."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app, public_api
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.intelligence import AgentSuggestion
from app.models.job_role import JobRole
from app.models.public_api import ApiKey, ApiUsage
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, get_current_tenant
from app.public_api import base as api_base
from app.public_api import keys as key_service

from tests.conftest import _create_user
from tests.test_public import _make_docx_bytes

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

API = "/api/public/v1"


def _tenant():
    return get_current_tenant() or TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


@pytest.fixture()
def owner(db_session):
    return _create_user(db_session, role="admin", email=f"api-owner-{uuid.uuid4().hex[:6]}@example.com")


@pytest.fixture()
def api(db_session, monkeypatch):
    """A client for the real app (middlewares + the mounted public app), every session = the test's transaction."""

    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    public_api.dependency_overrides[get_db] = _db
    monkeypatch.setattr(api_base, "USAGE_SESSION", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    public_api.dependency_overrides.clear()


def _key(db_session, owner, scopes=("jobs", "candidates", "screening", "scheduling", "cards"), **kw):
    from app.platform.tenancy.middleware import TenantResolverMiddleware  # noqa: F401 -- same tenant as the requests

    row, full = key_service.create_key(db_session, _request_tenant(db_session), owner, name="ATS", scopes=list(scopes), **kw)
    return row, {"Authorization": f"Bearer {full}"}


def _request_tenant(db_session):
    """The tenant the middleware resolves for TestClient requests (single mode: the only one)."""
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant

    cp = ControlPlaneSessionLocal()
    try:
        t = cp.query(Tenant).order_by(Tenant.created_at.asc()).first()
        return TenantContext(tenant_id=t.id, slug=t.slug, isolation=t.isolation)
    finally:
        cp.close()


def _job(db_session, owner, **kw):
    job = JobRole(title=f"API Role {uuid.uuid4().hex[:4]}", status=kw.pop("status", "published"), jd_text=kw.pop("jd_text", "A" * 60), created_by=owner.id,
                  salary_band_min=800000, salary_band_max=1200000, technical_skills_must_have=["python", "fastapi"], **kw)
    db_session.add(job)
    db_session.commit()
    return job


def _application(db_session, owner, status="screened"):
    job = _job(db_session, owner)
    cand = Candidate(full_name="Meera Iyer", email=f"meera-{uuid.uuid4().hex[:6]}@example.com")
    db_session.add(cand)
    db_session.commit()
    a = Application(job_role_id=job.id, candidate_id=cand.id, status=status, composite_score=81.25)
    db_session.add(a)
    db_session.commit()
    return a


# ---------------------------------------------------------------- keys and errors


def test_key_is_shown_once_and_only_its_hash_is_kept(db_session, owner):
    row, full = key_service.create_key(db_session, _request_tenant(db_session), owner, name="ATS", scopes=["jobs"])
    assert full.startswith("hra_live_") and row.prefix == full[:17] and row.mode == "live"
    assert row.secret_hash == hashlib.sha256(full.encode()).hexdigest() and full not in (row.secret_hash, row.prefix)
    with pytest.raises(ValueError):
        key_service.create_key(db_session, _request_tenant(db_session), owner, name="x", scopes=["everything"])


@pytest.mark.parametrize("header, code", [(None, "missing_key"), ("Bearer nope", "invalid_key"), ("Bearer hra_live_deadbeefWRONGSECRETxxxxxxxxxxxx", "invalid_key")])
def test_missing_or_wrong_key_is_401_in_the_error_shape(api, header, code):
    r = api.get(f"{API}/jobs", headers={"Authorization": header} if header else {})
    assert r.status_code == 401 and r.json()["error"]["code"] == code and r.json()["error"]["message"]


def test_revoked_and_expired_keys_stop_working(api, db_session, owner):
    row, h = _key(db_session, owner)
    assert api.get(f"{API}/jobs", headers=h).status_code == 200
    key_service.revoke(db_session, row)
    assert api.get(f"{API}/jobs", headers=h).json()["error"]["code"] == "revoked_key"

    row2, h2 = _key(db_session, owner)
    row2.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    r = api.get(f"{API}/jobs", headers=h2)
    assert r.status_code == 401 and r.json()["error"]["code"] == "expired_key"


def test_a_key_without_the_scope_is_403(api, db_session, owner):
    _, h = _key(db_session, owner, scopes=("screening",))
    r = api.get(f"{API}/jobs", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "missing_scope"


def test_a_key_is_looked_up_only_in_its_own_company(db_session, owner):
    _, full = key_service.create_key(db_session, _request_tenant(db_session), owner, name="ATS", scopes=["jobs"])
    other = TenantContext(tenant_id=uuid.uuid4(), slug="other-co", isolation="dedicated_db")
    with pytest.raises(key_service.KeyError_) as e:
        key_service.authenticate(db_session, other, full)
    assert e.value.status == 401


def test_test_keys_only_on_the_sandbox_and_live_keys_never_there(db_session, owner):
    live_tenant = _request_tenant(db_session)
    sandbox = TenantContext(tenant_id=live_tenant.tenant_id, slug="sandbox", isolation="dedicated_db")
    row, test_key = key_service.create_key(db_session, sandbox, owner, name="Sandbox", scopes=["jobs"])
    assert row.mode == "test" and test_key.startswith("hra_test_")
    assert key_service.authenticate(db_session, sandbox, test_key)[0].id == row.id
    with pytest.raises(key_service.KeyError_) as e:
        key_service.authenticate(db_session, live_tenant, test_key)  # a test key never reaches live data
    assert e.value.status == 403 and e.value.code == "wrong_mode"
    _, live_key = key_service.create_key(db_session, live_tenant, owner, name="Live", scopes=["jobs"])
    with pytest.raises(key_service.KeyError_) as e:
        key_service.authenticate(db_session, sandbox, live_key)
    assert e.value.code == "wrong_mode"


def test_a_module_the_company_has_not_activated_is_refused(api, db_session, owner, monkeypatch):
    """Proof 30.2h: the sandbox (every module off) could create a job through the API."""
    from app.platform import module_status

    _, h = _key(db_session, owner)
    monkeypatch.setattr(module_status, "is_active", lambda db, tenant, key: key != "jobs")
    r = api.post(f"{API}/jobs", headers=h, json={"title": "Not yet"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "module_not_active"
    assert db_session.query(JobRole).filter(JobRole.title == "Not yet").count() == 0
    assert api.get(f"{API}/cards", headers=h).status_code == 200  # cards have no module of their own


def test_rate_limit_answers_429_with_retry_after(api, db_session, owner, monkeypatch):
    from app.platform.settings.resolver import SettingsService

    real = SettingsService.get
    monkeypatch.setattr(SettingsService, "get", lambda self, key, ctx=None, *a, **k: 2 if key == "platform.api.rate_limit_per_minute" else real(self, key, ctx, *a, **k))
    _, h = _key(db_session, owner)
    codes = [api.get(f"{API}/jobs", headers=h).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = api.get(f"{API}/jobs", headers=h)
    assert r.json()["error"]["code"] == "rate_limited" and 1 <= int(r.headers["Retry-After"]) <= 60


def test_every_call_is_metered(api, db_session, owner):
    row, h = _key(db_session, owner)
    api.get(f"{API}/jobs", headers=h)
    api.get(f"{API}/jobs/{uuid.uuid4()}", headers=h)
    rows = db_session.query(ApiUsage).filter(ApiUsage.api_key_id == row.id).order_by(ApiUsage.created_at).all()
    assert [(u.method, u.status_code) for u in rows] == [("GET", 200), ("GET", 404)] and all(u.ms >= 0 for u in rows)
    assert db_session.get(ApiKey, row.id).last_used_at is not None


def test_validation_errors_use_the_error_shape(api, db_session, owner):
    _, h = _key(db_session, owner)
    r = api.post(f"{API}/jobs", headers=h, json={"title": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid" and "title" in r.json()["error"]["message"]


def test_an_unexpected_error_keeps_the_error_shape_and_is_metered(api, db_session, owner, monkeypatch):
    """Proof 30.2h: with no AI connection the endpoint answered a plain-text 'Internal Server Error'."""
    from app.platform.ai import governance
    from app.platform.connectors.router import NoConnectionForPurposeError

    row, h = _key(db_session, owner)
    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, f: True)

    def no_ai(*a, **k):
        raise NoConnectionForPurposeError("The AI service isn't connected yet")

    monkeypatch.setattr(governance, "governed_complete", no_ai)
    r = api.post(f"{API}/jd-drafts", headers=h, json={"title": "Data Engineer"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"

    monkeypatch.setattr(governance, "governed_complete", lambda *a, **k: 1 / 0)
    r = api.post(f"{API}/jd-drafts", headers=h, json={"title": "Data Engineer"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "server_error"
    assert [u.status_code for u in db_session.query(ApiUsage).filter(ApiUsage.api_key_id == row.id).order_by(ApiUsage.created_at)] == [503, 500]


def test_public_openapi_lists_only_public_endpoints(api):
    paths = api.get(f"{API}/openapi.json").json()["paths"]
    assert "/jobs" in paths and "/cards/{card_id}/decision" in paths and not any(p.startswith("/api/") for p in paths)
    assert api.get(f"{API}/docs").status_code == 200
    assert not any("public/v1" in p for p in app.openapi()["paths"])


# ---------------------------------------------------------------- jobs


def test_create_job_is_the_screens_create_and_never_publishes(api, db_session, owner):
    from app.models.audit_log import AuditLog

    _, h = _key(db_session, owner)
    r = api.post(f"{API}/jobs", headers=h, json={"title": "Platform Engineer", "location": "Chennai", "technical_skills_must_have": ["go"]})
    assert r.status_code == 201, r.text
    job = db_session.get(JobRole, uuid.UUID(r.json()["id"]))
    assert job.status == "draft" and job.created_by == owner.id
    assert db_session.query(AuditLog).filter(AuditLog.entity_id == job.id, AuditLog.action == "job_role_created").count() == 1  # the Job agent wakes on it
    assert api.get(f"{API}/jobs/{job.id}", headers=h).json()["status"] == "draft"


def test_idempotent_post_creates_one_job(api, db_session, owner):
    _, h = _key(db_session, owner)
    hk = {**h, "Idempotency-Key": f"k-{uuid.uuid4().hex}"}
    a = api.post(f"{API}/jobs", headers=hk, json={"title": "Idem Role"})
    b = api.post(f"{API}/jobs", headers=hk, json={"title": "Idem Role"})
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"] and b.headers.get("Idempotent-Replay") == "true"
    assert db_session.query(JobRole).filter(JobRole.title == "Idem Role").count() == 1
    c = api.post(f"{API}/jd-drafts", headers=hk, json={"title": "Other path"})
    assert c.status_code == 409 and c.json()["error"]["code"] == "idempotency_key_reused"


def test_salary_band_only_with_the_sensitive_scope(api, db_session, owner):
    job = _job(db_session, owner)
    _, plain = _key(db_session, owner)
    _, sens = _key(db_session, owner, scopes=("jobs", "sensitive"))
    assert api.get(f"{API}/jobs/{job.id}", headers=plain).json()["salary_band"] is None
    assert api.get(f"{API}/jobs/{job.id}", headers=sens).json()["salary_band"] == {"min": 800000, "max": 1200000}


def test_jd_draft_uses_the_job_agents_drafting(api, db_session, owner, monkeypatch):
    from types import SimpleNamespace

    from app.platform.ai import governance

    calls = []
    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, f: True)
    monkeypatch.setattr(governance, "governed_complete", lambda db, tenant, **kw: calls.append(kw) or SimpleNamespace(text="Drafted JD", decision_log_id=None))
    _, h = _key(db_session, owner)
    r = api.post(f"{API}/jd-drafts", headers=h, json={"title": "Data Engineer", "technical_skills_must_have": ["spark"]})
    assert r.status_code == 200 and r.json()["jd_text"] == "Drafted JD"
    assert calls[0]["feature"] == "agents.job" and "spark" in calls[0]["messages"][0]["content"]

    monkeypatch.setattr(governance, "feature_enabled", lambda db, tenant, f: False)
    assert api.post(f"{API}/jd-drafts", headers=h, json={"title": "Data Engineer"}).json()["error"]["code"] == "ai_off"


# ---------------------------------------------------------------- screening and applications


def test_screening_scores_against_a_job_without_storing_anything(api, db_session, owner, monkeypatch):
    import app.ai_services.resume_matcher as matcher
    import app.ai_services.resume_parser as parser

    monkeypatch.setattr(parser, "parse_resume", lambda text, data=None, name=None: {"skills": ["python"], "certificates": [], "location": "Chennai"})
    monkeypatch.setattr(matcher, "match_resume", lambda jd, parsed, loc=None, job_loc=None: {"match_score": 74, "location_score": 100, "recommendation": "Good backend fit"})
    job = _job(db_session, owner, knockout_questions_json=[{"question": "Can you work from Chennai?", "disqualify_on": "No"}])
    before = db_session.query(Application).count()
    _, h = _key(db_session, owner, scopes=("screening",))
    resume = "Kiran Das, Chennai. Python developer for five years: Django services, REST APIs, PostgreSQL, pytest, code reviews."
    r = api.post(f"{API}/screenings", headers=h, data={"resume_text": resume, "job_id": str(job.id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score"] == 74 and "fastapi" in body["missing_skills"] and body["knockouts"][0]["question"].startswith("Can you")
    assert "Good backend fit" in body["reasons"] and db_session.query(Application).count() == before
    assert api.post(f"{API}/screenings", headers=h, data={"resume_text": "x"}).json()["error"]["code"] == "invalid"  # no JD
    short = api.post(f"{API}/screenings", headers=h, data={"resume_text": "Python, 5 years", "job_id": str(job.id)})
    assert short.status_code == 422 and short.json()["error"]["code"] == "resume_too_short"  # proof 30.2h


def test_screening_says_why_the_ai_refused(api, db_session, owner, monkeypatch):
    """Proof 30.2h: the sandbox answered "The resume could not be read: ResumeParsingError" - the reason was hidden."""
    import app.ai_services.resume_parser as parser

    def blocked(*a, **k):
        raise parser.ResumeParsingError("AI usage is paused for this company (Settings > Integrations > AI Intelligence)", "AI_LIMIT")

    monkeypatch.setattr(parser, "parse_resume", blocked)
    _, h = _key(db_session, owner, scopes=("screening",))
    r = api.post(f"{API}/screenings", headers=h, data={"resume_text": "Python developer " * 10, "jd_text": "J" * 40})
    assert r.status_code == 503 and r.json()["error"] == {"code": "ai_unavailable",
                                                          "message": "AI usage is paused for this company (Settings > Integrations > AI Intelligence)"}


def test_apply_goes_through_the_careers_apply_path(api, db_session, owner, monkeypatch):
    import app.public.router as careers

    monkeypatch.setattr(careers, "_parse_resume_in_background", lambda *a, **k: None)  # no AI in the test
    job = _job(db_session, owner)
    _, h = _key(db_session, owner, scopes=("candidates",))
    form = {"full_name": "Ravi Kumar", "email": "ravi.api@example.com", "consent": "true", "consent_text": "I agree that my data is processed for hiring.",
            "expected_ctc": "1000000", "notice_period_days": "30"}
    files = {"resume": ("ravi.docx", _make_docx_bytes("Ravi Kumar, ravi.api@example.com, Python, FastAPI"), DOCX)}
    r = api.post(f"{API}/jobs/{job.id}/applications", headers=h, data=form, files=files)
    assert r.status_code == 201, r.text
    app_id = r.json()["application_id"]
    assert db_session.get(Application, uuid.UUID(app_id)).job_role_id == job.id

    files = {"resume": ("ravi.docx", _make_docx_bytes("Ravi Kumar, ravi.api@example.com, Python, FastAPI"), DOCX)}
    dup = api.post(f"{API}/jobs/{job.id}/applications", headers=h, data=form, files=files)
    assert dup.status_code in (400, 409) and dup.json()["error"]["message"]  # the careers page's duplicate block

    files = {"resume": ("ravi.docx", _make_docx_bytes("Ravi Kumar, ravi.api@example.com, Python, FastAPI"), DOCX)}
    no_consent = api.post(f"{API}/jobs/{job.id}/applications", headers=h, data={**form, "email": "x@example.com", "consent": "false"}, files=files)
    assert no_consent.status_code == 422 and no_consent.json()["error"]["code"] == "consent_required"


def test_application_status_and_journey(api, db_session, owner):
    from app.hr_agents.autopilot.core import Run, record

    a = _application(db_session, owner)
    record(db_session, _tenant(), Run("event", "x"), agent="screening", action="propose_shortlist", outcome="proposed", entity_type="application",
           entity_id=a.id, summary="Prepared a shortlist card")
    card = AgentSuggestion(tenant_id=a.tenant_id, agent="recruiter", kind="agent_shortlist", title="Shortlist Meera", payload_json={},
                           reviewer_permission="recruitment.application.edit", entity_type="application", entity_id=a.id)
    db_session.add(card)
    db_session.commit()
    _, h = _key(db_session, owner, scopes=("candidates",))
    body = api.get(f"{API}/applications/{a.id}", headers=h).json()
    assert body["status"] == "screened" and body["next_step"] == "Waiting for the shortlist decision" and body["waiting_card"]["id"] == str(card.id)
    assert [i["action"] for i in api.get(f"{API}/applications/{a.id}/journey", headers=h).json()["items"]] == ["propose_shortlist"]
    assert api.get(f"{API}/applications/{uuid.uuid4()}", headers=h).status_code == 404


def test_send_interview_times_is_the_screens_button(api, db_session, owner, monkeypatch):
    from app.interview_scheduling import automation

    calls = []
    monkeypatch.setattr(automation, "start", lambda db, t, a, u, **kw: calls.append((a.id, u.id, kw)) or {"outcome": "started"})
    a = _application(db_session, owner, status="hr_selected")
    _, h = _key(db_session, owner, scopes=("scheduling",))
    r = api.post(f"{API}/applications/{a.id}/interview-scheduling", headers=h)
    assert r.status_code == 200 and calls == [(a.id, owner.id, {"trigger": "send_now", "force": True})]
    monkeypatch.setattr(automation, "start", lambda *a, **k: {"outcome": "problem", "reason": "No interviewer has free time"})
    r = api.post(f"{API}/applications/{a.id}/interview-scheduling", headers=h)
    assert r.status_code == 409 and r.json()["error"]["message"] == "No interviewer has free time"


# ---------------------------------------------------------------- cards


def _jd_card(db_session, job, text):
    from app.agents.service import suggest

    return suggest(db_session, _tenant(), agent="recruiter", kind="jd_draft", title=f"JD for {job.title}", payload={"jd_text": text},
                   reviewer_permission="recruitment.job.edit", entity_type="job_role", entity_id=job.id)


def test_card_decision_by_api_equals_the_screen(api, db_session, owner, client):
    job_a, job_b = _job(db_session, owner, jd_text=None, status="draft"), _job(db_session, owner, jd_text=None, status="draft")
    card_a, card_b = _jd_card(db_session, job_a, "JD text"), _jd_card(db_session, job_b, "JD text")
    _, h = _key(db_session, owner, scopes=("cards",))
    assert str(card_a.id) in {c["id"] for c in api.get(f"{API}/cards", headers=h).json()["items"]}

    by_api = api.post(f"{API}/cards/{card_a.id}/decision", headers=h, json={"action": "approve"})
    by_screen = client.post(f"/api/v1/intelligence/agents/suggestions/{card_b.id}/decision", json={"action": "approve"})
    assert by_api.status_code == 200 and by_screen.status_code == 200, (by_api.text, by_screen.text)
    db_session.refresh(job_a)
    db_session.refresh(job_b)
    assert by_api.json()["status"] == by_screen.json()["status"] == "approved" and job_a.jd_text == job_b.jd_text == "JD text"
    again = api.post(f"{API}/cards/{card_a.id}/decision", headers=h, json={"action": "approve"})
    assert again.status_code == 409 and "already approved" in again.json()["error"]["message"]


def test_card_edit_needs_the_changed_card_and_reviewer_rules_apply(api, db_session, owner):
    job = _job(db_session, owner, jd_text=None, status="draft")
    card = _jd_card(db_session, job, "Draft")
    _, h = _key(db_session, owner, scopes=("cards",))
    assert api.post(f"{API}/cards/{card.id}/decision", headers=h, json={"action": "edit"}).status_code == 422
    r = api.post(f"{API}/cards/{card.id}/decision", headers=h, json={"action": "edit", "payload": {"jd_text": "Changed"}})
    db_session.refresh(job)
    assert r.json()["status"] == "edited" and job.jd_text == "Changed"

    interviewer = _create_user(db_session, role="interviewer", email=f"iv-{uuid.uuid4().hex[:6]}@example.com")
    card2 = _jd_card(db_session, _job(db_session, owner, jd_text=None, status="draft"), "Draft")
    _, hi = _key(db_session, interviewer, scopes=("cards",))
    r = api.post(f"{API}/cards/{card2.id}/decision", headers=hi, json={"action": "approve"})
    assert r.status_code == 403  # the key acts as its creator: an interviewer cannot decide a job card
