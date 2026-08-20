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
    # No "experience_score"/"skill_match_pct"/"missing_skills" keys -- match_resume (the
    # AI call) no longer produces any of these; run_screening computes them itself via
    # compute_experience_score/compute_skills_score and overwrites whatever's in `result`
    # for those keys, so these tests' jobs/candidates deliberately carry no
    # experience_min_years/max_years/total_experience_years or skill categories, which
    # both compute functions treat as "no requirement configured" -> a fixed 100 (see
    # test_compute_experience_score_*/test_compute_skills_score_* below for the cases
    # that actually vary these inputs).
    result = {
        "match_score": 80,
        "location_score": 80,
        "certificates_score": 80,
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


# --- compute_experience_score: deterministic replacement for the old AI-judged score ---


def test_compute_experience_score_no_requirement_configured_is_full_score():
    # Both bounds null -- same "absence of a requirement is not a penalty" convention as
    # location_score/certificates_score, regardless of the candidate's own years.
    assert screening_service.compute_experience_score(2, None, None) == 100
    assert screening_service.compute_experience_score(None, None, None) == 100


def test_compute_experience_score_within_range_is_full_score():
    assert screening_service.compute_experience_score(4, 3, 5) == 100
    assert screening_service.compute_experience_score(3, 3, 5) == 100  # at the min boundary
    assert screening_service.compute_experience_score(5, 3, 5) == 100  # at the max boundary


def test_compute_experience_score_open_ended_max_only_checks_the_floor():
    # job_max_years null means "X+ years" -- any candidate at or above the minimum is a
    # full score no matter how much more experience they have.
    assert screening_service.compute_experience_score(5, 5, None) == 100
    assert screening_service.compute_experience_score(20, 5, None) == 100


def test_compute_experience_score_falls_off_below_min():
    # 15 points off per year of shortfall, floored at 0.
    assert screening_service.compute_experience_score(4, 5, 8) == 85
    assert screening_service.compute_experience_score(3, 5, 8) == 70
    assert screening_service.compute_experience_score(0, 5, 8) == max(0, 100 - 5 * 15)


def test_compute_experience_score_falls_off_above_max():
    assert screening_service.compute_experience_score(9, 5, 8) == 85
    assert screening_service.compute_experience_score(10, 5, 8) == 70


def test_compute_experience_score_floors_at_zero_well_outside_range():
    assert screening_service.compute_experience_score(0, 20, 25) == 0


def test_compute_experience_score_unknown_candidate_years_is_neutral_when_requirement_exists():
    # Distinct from both a confirmed match (100) and a confirmed mismatch (a low falloff
    # score) -- the candidate's own years just couldn't be determined.
    assert screening_service.compute_experience_score(None, 3, 5) == 50
    assert screening_service.compute_experience_score(None, 5, None) == 50


# --- compute_skills_score: deterministic replacement for the old AI-judged skill_match_pct ---


def test_compute_skills_score_no_categories_configured_is_full_score():
    # No requirement in any of the 4 categories -- same "absence of a requirement is not
    # a penalty" convention as location_score/certificates_score/experience_score.
    result = screening_service.compute_skills_score(["Python"], None, None, None, None)
    assert result["score"] == 100
    assert result["missing_required"] == []
    assert result["missing_preferred"] == []


def test_compute_skills_score_full_match_across_all_categories_is_100():
    result = screening_service.compute_skills_score(
        ["Python", "FastAPI", "Docker", "Communication"],
        technical_must_have=["Python"], technical_good_to_have=["FastAPI"],
        soft_must_have=["Communication"], soft_good_to_have=["Docker"],
    )
    assert result["score"] == 100
    assert result["missing_required"] == []
    assert result["missing_preferred"] == []


def test_compute_skills_score_missing_must_have_technical_costs_the_most():
    # 100% good-to-have/soft coverage, 0% technical-must-have -> loses exactly the 50-point
    # technical_must_have weight.
    result = screening_service.compute_skills_score(
        [],
        technical_must_have=["Python"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 50
    assert result["missing_required"] == ["Python"]
    assert result["missing_preferred"] == []


def test_compute_skills_score_missing_good_to_have_technical_costs_less_than_must_have():
    # Same setup as above but the unmet skill is technical_good_to_have (weight 20, not 50).
    result = screening_service.compute_skills_score(
        [],
        technical_must_have=None, technical_good_to_have=["Kubernetes"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 80
    assert result["missing_required"] == []
    assert result["missing_preferred"] == ["Kubernetes"]


def test_compute_skills_score_missing_soft_must_have_weighs_the_same_as_technical_good_to_have():
    # Both technical_good_to_have and soft_must_have are weighted 20 -- confirms the
    # "roughly equal next tier" ordering the weights were chosen for.
    technical_good_to_have_result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=["Kubernetes"], soft_must_have=None, soft_good_to_have=None,
    )
    soft_must_have_result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=None, soft_must_have=["Leadership"], soft_good_to_have=None,
    )
    assert technical_good_to_have_result["score"] == soft_must_have_result["score"] == 80


def test_compute_skills_score_missing_good_to_have_soft_costs_the_least():
    result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=None, soft_must_have=None, soft_good_to_have=["Empathy"],
    )
    assert result["score"] == 90
    assert result["missing_required"] == []
    assert result["missing_preferred"] == ["Empathy"]


def test_compute_skills_score_matching_is_case_and_whitespace_insensitive():
    result = screening_service.compute_skills_score(
        ["  PYTHON  "], technical_must_have=["python"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 100
    assert result["missing_required"] == []


def test_compute_skills_score_missing_required_combines_technical_and_soft_must_have():
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Python"], technical_good_to_have=None,
        soft_must_have=["Communication"], soft_good_to_have=None,
    )
    assert set(result["missing_required"]) == {"Python", "Communication"}


# --- run_screening: the deterministic experience_score actually feeds the composite ---


def test_run_screening_uses_real_experience_range_against_candidate_years(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(db_session, experience_min_years=3, experience_max_years=5)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"], "total_experience_years": 4})
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # Candidate's 4 years falls within [3, 5] -> experience_score 100 -> composite 100.
    assert float(result.composite_score) == 100.0

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 100


def test_run_screening_penalizes_candidate_below_the_jobs_min_years(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(db_session, experience_min_years=5, experience_max_years=8)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"], "total_experience_years": 3})
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # 2 years short of the 5-year minimum -> 100 - 2*15 = 70 -> composite (100*4 + 70)/5.
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 70
    assert float(result.composite_score) == 94.0


def test_run_screening_neutral_score_when_candidate_years_unparsed_but_job_has_a_range(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(db_session, experience_min_years=3, experience_max_years=5)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})  # no total_experience_years
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 50
    assert float(result.composite_score) == 90.0


# --- run_screening: the deterministic skill_match_pct actually feeds the composite,
# and Remarks (via missing_required_skills/missing_preferred_skills) can tell severity apart ---


def test_run_screening_uses_real_skill_categories_against_candidate_skills(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(
        db_session, technical_skills_must_have=["Python"], technical_skills_good_to_have=["Kubernetes"],
        soft_skills_must_have=["Communication"], soft_skills_good_to_have=["Empathy"],
    )
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python", "Communication"]}
    )
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    # Both must-have categories matched (50 + 20), both good-to-have categories missed
    # (0 + 0) -> skill_match_pct = 70. Composite = (100_experience + 70_skills + 100*3) / 5.
    assert audit_entry.details["skills_score"] == 70
    assert set(audit_entry.details["missing_required_skills"]) == set()
    assert set(audit_entry.details["missing_preferred_skills"]) == {"Kubernetes", "Empathy"}
    assert float(result.composite_score) == 94.0


def test_run_screening_missing_required_skills_recorded_distinctly_from_preferred(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
    )
    job = _make_job(
        db_session, technical_skills_must_have=["Python", "SQL"], technical_skills_good_to_have=["Docker"],
    )
    candidate = _make_candidate(db_session, parsed_fields={"skills": []})
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert set(audit_entry.details["missing_required_skills"]) == {"Python", "SQL"}
    assert audit_entry.details["missing_preferred_skills"] == ["Docker"]
    # missing_skills (the flat, backward-compatible union stored on Application) still
    # carries both severities together.
    assert set(audit_entry.details["missing_skills"]) == {"Python", "SQL", "Docker"}


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

    # (80 + 80 + 80 -- the three AI-scored factors -- + 100 + 100, the deterministic
    # experience_score/skill_match_pct for a job with no experience range or skill
    # categories configured) / 5.
    assert result.status == "screened"
    assert float(result.composite_score) == 88.0


def test_run_screening_at_max_boundary_advances_to_screened_same_as_in_range(db_session, monkeypatch):
    # Design decision: a score at or above the configured max threshold gets identical
    # treatment to a score within [min, max] -- both become 'screened', no separate
    # high-priority outcome. Default max seeded by migration e1f3a7c9b2d4 is 100.
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100, certificates_score=100),
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
        lambda *a, **k: _fake_result(match_score=10, location_score=10, certificates_score=10),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # (10 + 10 + 10 + 100 + 100 -- no experience range or skill categories configured)
    # / 5 = 46.
    assert float(result.composite_score) == 46.0
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
        lambda *a, **k: _fake_result(match_score=55, location_score=55, certificates_score=55),
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
    # (80 * 3 AI-scored factors + 100 + 100, the deterministic experience_score/
    # skill_match_pct for a job with no experience range or skill categories
    # configured) / 5.
    assert body["composite_score"] == 88.0

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
