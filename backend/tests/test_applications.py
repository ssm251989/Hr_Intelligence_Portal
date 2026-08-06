import uuid

from app.core.crypto import encrypt
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user_integration import UserIntegration


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
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


# --- email notification wiring (POST /applications) --------------------------


def test_create_application_triggers_notification_when_owner_enabled_and_connected(
    client, db_session, make_auth_headers, monkeypatch
):
    headers = make_auth_headers(role="recruiter", email="owner@example.com")
    # The token's subject is the user id -- fetch it back out to attach as job.created_by.
    from app.core.security import decode_access_token

    owner_id = uuid.UUID(decode_access_token(headers["Authorization"].split(" ")[1])["sub"])
    db_session.add(UserIntegration(user_id=owner_id, provider="google", refresh_token=encrypt("refresh-token")))
    db_session.commit()
    job = _make_job(db_session, created_by=owner_id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    captured = {}
    monkeypatch.setattr(
        "app.jobs.service.send_email",
        lambda refresh_token, **kwargs: captured.update(kwargs) or "msg_1",
    )

    response = client.post(
        "/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)}
    )

    assert response.status_code == 201
    assert captured.get("to") == "owner@example.com"


def test_create_application_succeeds_even_if_notification_helper_would_fail(client, db_session, monkeypatch):
    # No integration connected at all -- create_application must still succeed; the
    # notification is fire-and-forget and must never block the response.
    job = _make_job(db_session, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    response = client.post(
        "/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)}
    )

    assert response.status_code == 201


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
