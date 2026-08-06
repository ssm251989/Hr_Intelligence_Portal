import uuid

from app.ai_services.jd_generator import JDGenerationError
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
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


# --- /jobs/{id}/publish ---


def test_publish_with_career_portal_sets_status_published(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={"naukri": False, "linkedin": False, "career_portal": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["published_platforms"] == {"naukri": False, "linkedin": False, "career_portal": True}


def test_publish_without_career_portal_does_not_set_published(client, db_session):
    job = _make_job(db_session, status="published")

    # Unchecking Career Portal on an already-published job must revert it --
    # "keeps/reverts it to a non-published state" per the wizard's publish step.
    response = client.post(
        f"/jobs/{job.id}/publish",
        json={"naukri": True, "linkedin": True, "career_portal": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready_for_publishing"
    assert body["status"] != "published"


def test_publish_naukri_and_linkedin_only_record_intent(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={"naukri": True, "linkedin": True, "career_portal": False},
    )

    assert response.status_code == 200
    body = response.json()
    # Naukri/LinkedIn have no posting API access -- checking them only stores intent,
    # it must never be the thing that flips status to published.
    assert body["published_platforms"] == {"naukri": True, "linkedin": True, "career_portal": False}
    assert body["status"] == "ready_for_publishing"


def test_publish_stores_placeholder_settings_and_deadline(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": False,
            "linkedin": False,
            "career_portal": True,
            "email_notifications": True,
            "application_deadline": "2026-09-30",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["publish_settings"] == {
        "email_notifications": True,
        "application_deadline": "2026-09-30",
    }


def test_publish_stores_posting_urls(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": True,
            "linkedin": True,
            "career_portal": False,
            "posting_url_naukri": "https://www.naukri.com/job-listings-123",
            "posting_url_linkedin": "https://www.linkedin.com/jobs/view/456",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["posting_url_naukri"] == "https://www.naukri.com/job-listings-123"
    assert body["posting_url_linkedin"] == "https://www.linkedin.com/jobs/view/456"


def test_generic_patch_can_update_posting_urls_later(client, db_session):
    # A recruiter pastes the posting URL after manually posting -- separate from
    # the initial /publish call, since they won't have it yet at that point.
    job = _make_job(db_session, status="published")

    response = client.patch(f"/jobs/{job.id}", json={"posting_url_naukri": "https://www.naukri.com/job-999"})

    assert response.status_code == 200
    assert response.json()["posting_url_naukri"] == "https://www.naukri.com/job-999"


def test_publish_logs_audit_entry_with_status_transition(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")

    client.post(f"/jobs/{job.id}/publish", json={"naukri": False, "linkedin": False, "career_portal": True})

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "job_platforms_published")
        .one_or_none()
    )
    assert entry is not None
    assert entry.details["previous_status"] == "ready_for_publishing"
    assert entry.details["new_status"] == "published"


def test_publish_not_found(client):
    response = client.post(
        f"/jobs/{uuid.uuid4()}/publish",
        json={"naukri": False, "linkedin": False, "career_portal": True},
    )
    assert response.status_code == 404


# --- application deadline enforcement (lazy, on read) ---


def test_get_job_closes_published_job_past_deadline(client, db_session):
    job = _make_job(db_session, status="published", publish_settings={"application_deadline": "2020-01-01"})

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "closed"

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "job_auto_closed_deadline_passed")
        .one_or_none()
    )
    assert entry is not None
    assert entry.details["previous_status"] == "published"


def test_get_job_leaves_published_job_before_deadline_alone(client, db_session):
    job = _make_job(db_session, status="published", publish_settings={"application_deadline": "2099-01-01"})

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "published"


def test_get_job_ignores_deadline_when_status_is_not_published(client, db_session):
    # A draft job with a (irrelevant) past deadline must not be auto-closed --
    # the deadline only governs an already-published job's lifecycle.
    job = _make_job(db_session, status="draft", publish_settings={"application_deadline": "2020-01-01"})

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "draft"


def test_list_jobs_closes_expired_jobs_too(client, db_session):
    job = _make_job(db_session, status="published", publish_settings={"application_deadline": "2020-01-01"})

    client.get("/jobs")

    db_session.refresh(job)
    assert job.status == "closed"
