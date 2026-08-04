import uuid

from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session) -> JobRole:
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session) -> Candidate:
    candidate = Candidate(full_name="Jane Doe")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_create_application_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    response = client.post(
        "/applications",
        json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "received"
    assert body["job_role_id"] == str(job.id)
    assert body["candidate_id"] == str(candidate.id)


def test_create_application_missing_job_returns_404(client, db_session):
    candidate = _make_candidate(db_session)

    response = client.post(
        "/applications",
        json={"job_role_id": str(uuid.uuid4()), "candidate_id": str(candidate.id)},
    )

    assert response.status_code == 404


def test_create_application_missing_candidate_returns_404(client, db_session):
    job = _make_job(db_session)

    response = client.post(
        "/applications",
        json={"job_role_id": str(job.id), "candidate_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


def test_list_applications_filtered_by_job_role_id(client, db_session):
    job_a = _make_job(db_session)
    job_b = _make_job(db_session)
    candidate = _make_candidate(db_session)

    client.post("/applications", json={"job_role_id": str(job_a.id), "candidate_id": str(candidate.id)})
    client.post("/applications", json={"job_role_id": str(job_b.id), "candidate_id": str(candidate.id)})

    response = client.get("/applications", params={"job_role_id": str(job_a.id)})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["job_role_id"] == str(job_a.id)
