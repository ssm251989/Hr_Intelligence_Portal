import uuid

from app.ai_services.jd_generator import JDGenerationError
from app.models.job_role import JobRole


def _make_job(db_session) -> JobRole:
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_generate_job_description_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_generate_jd(inputs):
        raise JDGenerationError("Failed to generate job description: AI service timed out")

    monkeypatch.setattr("app.jobs.router.generate_jd", fake_generate_jd)

    job = _make_job(db_session)

    response = client.post(f"/jobs/{job.id}/generate-jd")

    assert response.status_code == 502


def test_generate_job_description_not_found(client):
    response = client.post(f"/jobs/{uuid.uuid4()}/generate-jd")
    assert response.status_code == 404
