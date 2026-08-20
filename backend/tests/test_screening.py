import uuid

from app.ai_services.candidate_ranker import CandidateRankingError
from app.ai_services.resume_matcher import ResumeMatchError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session, jd_text=None, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", jd_text=jd_text, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, parsed_fields=None, **kwargs) -> Candidate:
    candidate = Candidate(full_name="Jane Doe", parsed_fields=parsed_fields, **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, match_score=None, **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, match_score=match_score, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


# location_score=100, match_score=78 from the (mocked) AI call, plus three deterministic
# scores from test_screen_application_success's job/candidate fixtures below:
# experience_score=70 (2 years short of a 5-8 year requirement -> 100 - 2*15),
# skill_match_pct=80 (both technical_skills_must_have matched -> 50, the one
# technical_skills_good_to_have entry ("Kubernetes") missed -> 0 of 20, no soft
# categories configured -> full 20 + 10), and certificates_score=100 (no
# preferred_certifications configured on the job -- absence of a requirement is not a
# penalty) -> composite = (80+70+100+100+78)/5 = 85.6, comfortably above the default
# dashboard_min_score=60 seeded by migration e1f3a7c9b2d4, so screening these fixtures
# always auto-advances to 'screened' unless a test overrides a field to test otherwise.
FAKE_MATCH_RESULT = {
    "match_score": 78,
    "location_score": 100,
    "recommendation": "possible_fit",
}

FAKE_RANKING_RESULT = {
    "composite_score": 82,
    "rank_rationale": "Strong backend fundamentals with direct FastAPI experience.",
    "strengths": ["4 years Python", "Built production REST APIs"],
    "concerns": ["No Kubernetes experience"],
    "recommendation": "recommend",
}


def test_screen_application_success(client, db_session, monkeypatch):
    # The call now happens inside app.screening.service.run_screening, not the router
    # directly -- see app/screening/service.py.
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda jd_text, parsed_fields, candidate_location, job_location: FAKE_MATCH_RESULT,
    )

    job = _make_job(
        db_session, jd_text="We need a backend engineer skilled in Python and FastAPI.",
        experience_min_years=5, experience_max_years=8,
        technical_skills_must_have=["Python", "FastAPI"], technical_skills_good_to_have=["Kubernetes"],
    )
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python", "FastAPI"], "total_experience_years": 3}
    )
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 200
    body = response.json()
    assert body["match_score"] == 78
    assert body["skill_match_pct"] == 80
    assert body["missing_skills"] == ["Kubernetes"]
    assert body["composite_score"] == 85.6
    assert body["status"] == "screened"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details["skills_score"] == 80
    assert audit_entry.details["experience_score"] == 70
    assert audit_entry.details["location_score"] == 100
    assert audit_entry.details["certificates_score"] == 100
    assert audit_entry.details["resume_matcher_score"] == 78
    assert audit_entry.details["composite_score"] == 85.6
    assert audit_entry.details["missing_required_skills"] == []
    assert audit_entry.details["missing_preferred_skills"] == ["Kubernetes"]
    assert audit_entry.details["advanced"] is True
    assert audit_entry.details["previous_status"] == "received"
    assert audit_entry.details["new_status"] == "screened"


def test_screen_application_without_jd_returns_400(client, db_session):
    job = _make_job(db_session, jd_text=None)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 400


def test_screen_application_without_parsed_resume_returns_400(client, db_session):
    job = _make_job(db_session, jd_text="Backend role.")
    candidate = _make_candidate(db_session, parsed_fields=None)
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 400


def test_screen_application_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_match_resume(jd_text, parsed_fields, candidate_location, job_location):
        raise ResumeMatchError("Failed to match resume against job description: AI service timed out")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and FastAPI.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python", "FastAPI"]})
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 502

    # Safeguard: an AI failure must never silently leave a guessed score behind -- the
    # application stays completely untouched, still 'received'.
    db_session.refresh(application)
    assert application.status == "received"
    assert application.composite_score is None
    assert application.match_score is None

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_failed")
        .one_or_none()
    )
    assert audit_entry is not None
    assert "AI service timed out" in audit_entry.details["error"]


def test_screen_application_not_found_returns_404(client):
    response = client.post(f"/applications/{uuid.uuid4()}/screen")
    assert response.status_code == 404


def test_rank_application_success(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.router.rank_candidate",
        lambda jd_text, match_data, interview_feedback: FAKE_RANKING_RESULT,
    )

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and FastAPI.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python", "FastAPI"]})
    application = _make_application(db_session, job, candidate, match_score=78)

    response = client.post(f"/applications/{application.id}/rank")

    assert response.status_code == 200
    body = response.json()
    # match_score is set by the earlier screen step and must be untouched by ranking.
    assert body["match_score"] == 78
    # ranking_score holds the ranking step's own composite score, in its own column.
    assert body["ranking_score"] == 82
    assert body["match_score"] != body["ranking_score"]
    assert "Strong backend fundamentals" in body["ranking_rationale"]
    assert "Kubernetes" in body["ranking_rationale"]
    assert "recommend" in body["ranking_rationale"]

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_candidate_ranking_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == {**FAKE_RANKING_RESULT, "composite_score": 82.0}


def test_rank_application_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_rank_candidate(jd_text, match_data, interview_feedback):
        raise CandidateRankingError("Failed to rank candidate: AI service timed out")

    monkeypatch.setattr("app.screening.router.rank_candidate", fake_rank_candidate)

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and FastAPI.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python", "FastAPI"]})
    application = _make_application(db_session, job, candidate, match_score=78)

    response = client.post(f"/applications/{application.id}/rank")

    assert response.status_code == 502


def test_rank_application_before_screening_returns_400(client, db_session):
    job = _make_job(db_session, jd_text="Backend role.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application = _make_application(db_session, job, candidate, match_score=None)

    response = client.post(f"/applications/{application.id}/rank")

    assert response.status_code == 400
