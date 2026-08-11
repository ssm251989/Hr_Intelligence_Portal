import io
import uuid

from docx import Document

from app.ai_services.resume_matcher import ResumeMatchError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.screening_settings import ScreeningSettings
from app.screening import service as screening_service


def _make_job(db_session, jd_text="Backend role needing Python.", **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", jd_text=jd_text, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


_DEFAULT_PARSED_FIELDS = {"skills": ["Python"]}


def _make_candidate(db_session, parsed_fields=_DEFAULT_PARSED_FIELDS, **kwargs) -> Candidate:
    candidate = Candidate(full_name="Jane Doe", parsed_fields=parsed_fields, **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="received", **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _fake_result(**overrides) -> dict:
    result = {
        "match_score": 80,
        "skill_match_pct": 80,
        "experience_score": 80,
        "location_score": 80,
        "certificates_score": 80,
        "missing_skills": [],
        "recommendation": "strong_fit",
    }
    result.update(overrides)
    return result


# --- composite_score: pure function, equal weights ---


def test_composite_score_is_equal_weighted_average():
    result = {
        "skill_match_pct": 100,
        "experience_score": 0,
        "location_score": 50,
        "certificates_score": 50,
        "match_score": 100,
    }
    # (100 + 0 + 50 + 50 + 100) / 5 = 60 -- confirms all five factors count equally, not
    # some larger weight for e.g. match_score just because it's the "existing" one.
    assert screening_service.composite_score(result) == 60.0


def test_composite_score_all_equal_inputs_returns_same_value():
    result = {k: 73 for k in ["skill_match_pct", "experience_score", "location_score", "certificates_score", "match_score"]}
    assert screening_service.composite_score(result) == 73.0


def test_composite_score_changing_any_single_factor_moves_the_average_by_its_fifth():
    base = {"skill_match_pct": 60, "experience_score": 60, "location_score": 60, "certificates_score": 60, "match_score": 60}
    bumped = {**base, "certificates_score": 100}
    # +40 on one of five equally-weighted factors -> +8 on the average, not some other
    # fraction that would imply certificates_score carries more or less weight than peers.
    assert screening_service.composite_score(bumped) - screening_service.composite_score(base) == 8.0


# --- is_eligible_for_screening ---


def test_is_eligible_for_screening_true_only_for_received(db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    for status in ["screened", "hr_selected", "hr_rejected", "on_hold", "onboarding_completed"]:
        application = _make_application(db_session, job, candidate, status=status)
        assert screening_service.is_eligible_for_screening(application) is False
    received_app = _make_application(db_session, job, candidate, status="received")
    assert screening_service.is_eligible_for_screening(received_app) is True


# --- run_screening: threshold auto-advance, including the max-boundary equivalence ---


def test_run_screening_in_range_advances_to_screened(db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert result.status == "screened"
    assert float(result.composite_score) == 80.0


def test_run_screening_at_max_boundary_advances_to_screened_same_as_in_range(db_session, monkeypatch):
    # Design decision: a score at or above the configured max threshold gets identical
    # treatment to a score within [min, max] -- both become 'screened', no separate
    # high-priority outcome. Default max seeded by migration e1f3a7c9b2d4 is 100.
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, skill_match_pct=100, experience_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert float(result.composite_score) == 100.0
    assert result.status == "screened"


def test_run_screening_below_min_threshold_stays_received_but_is_still_scored(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=10, skill_match_pct=10, experience_score=10, location_score=10, certificates_score=10),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert float(result.composite_score) == 10.0
    assert result.status == "received"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["advanced"] is False
    assert audit_entry.details["new_status"] == "received"


def test_run_screening_respects_configured_threshold_not_just_the_default(db_session, monkeypatch):
    # A score of 55 is below the seeded default min (60) but above a lowered min (40) --
    # proves the threshold is actually read from screening_settings, not hardcoded.
    settings_row = db_session.get(ScreeningSettings, 1)
    settings_row.dashboard_min_score = 40
    db_session.commit()

    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=55, skill_match_pct=55, experience_score=55, location_score=55, certificates_score=55),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert result.status == "screened"


# --- attempt_auto_screen: the best-effort trigger used by the two automatic hooks ---


def test_attempt_auto_screen_skips_already_screened_application(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", composite_score=90)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []
    db_session.refresh(application)
    assert application.status == "screened"


def test_attempt_auto_screen_noop_when_job_has_no_jd_text(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session, jd_text=None)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []


def test_attempt_auto_screen_noop_when_candidate_not_parsed(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, parsed_fields=None)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []


def test_attempt_auto_screen_swallows_ai_failure(db_session, monkeypatch):
    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    db_session.refresh(application)
    assert application.status == "received"
    assert application.composite_score is None


# --- integration: the two real hook points fire automatically ---


def test_create_application_triggers_auto_screen_when_resume_already_parsed(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session, jd_text="Needs Python.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})

    response = client.post("/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "screened"
    assert body["composite_score"] == 80.0

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(body["id"]), AuditLog.action == "ai_screening_scored")
        .one_or_none()
    )
    assert audit_entry is not None


def test_create_application_does_not_fail_when_screening_ai_call_errors(client, db_session, monkeypatch):
    # The application-creation flow must succeed regardless of screening's own problems.
    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session, jd_text="Needs Python.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})

    response = client.post("/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)})

    assert response.status_code == 201
    assert response.json()["status"] == "received"


def test_parse_resume_triggers_auto_screen_for_existing_received_application(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    monkeypatch.setattr(
        "app.candidates.router.parse_resume",
        lambda raw_text: {"full_name": "Jane Doe", "email": "jane@example.com", "skills": ["Python"]},
    )
    job = _make_job(db_session, jd_text="Needs Python.")

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    # Application created before the resume is parsed (mirrors the career-portal path:
    # apply first, background-parse afterward).
    application_response = client.post(
        "/applications", json={"job_role_id": str(job.id), "candidate_id": candidate_id}
    )
    assert application_response.json()["status"] == "received"  # not parsed yet, so no auto-screen at creation time

    parse_response = client.post(f"/candidates/{candidate_id}/parse-resume")
    assert parse_response.status_code == 200

    application_id = application_response.json()["id"]
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(application_id), AuditLog.action == "ai_screening_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    refreshed = db_session.get(Application, uuid.UUID(application_id))
    assert refreshed.status == "screened"
