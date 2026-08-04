import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session, jd_text=None) -> JobRole:
    job = JobRole(title="Backend Engineer", jd_text=jd_text)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, parsed_fields=None) -> Candidate:
    candidate = Candidate(full_name="Jane Doe", parsed_fields=parsed_fields)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, match_score=None) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, match_score=match_score)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


FAKE_MATCH_RESULT = {
    "match_score": 78,
    "skill_match_pct": 65,
    "missing_skills": ["Kubernetes"],
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
    monkeypatch.setattr("app.screening.router.match_resume", lambda jd_text, parsed_fields: FAKE_MATCH_RESULT)

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and FastAPI.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python", "FastAPI"]})
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 200
    body = response.json()
    assert body["match_score"] == 78
    assert body["skill_match_pct"] == 65
    assert body["missing_skills"] == ["Kubernetes"]
    assert body["status"] == "screened"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_resume_matcher_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == FAKE_MATCH_RESULT


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


def test_rank_application_before_screening_returns_400(client, db_session):
    job = _make_job(db_session, jd_text="Backend role.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application = _make_application(db_session, job, candidate, match_score=None)

    response = client.post(f"/applications/{application.id}/rank")

    assert response.status_code == 400
