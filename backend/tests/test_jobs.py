import uuid
from datetime import datetime, timedelta, timezone

from app.ai_services.jd_generator import JDGenerationError
from app.core.crypto import encrypt
from app.integrations.linkedin import LinkedInError
from app.models.audit_log import AuditLog
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _connect_linkedin(db_session, user, expires_at=None, member_urn="urn:li:person:abc123") -> UserIntegration:
    integration = UserIntegration(
        user_id=user.id,
        provider="linkedin",
        refresh_token=encrypt("fake-access-token"),
        expires_at=expires_at,
        provider_metadata={"member_urn": member_urn},
    )
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def _admin_user(db_session) -> User:
    # The `client` fixture authenticates as this user (see conftest.py).
    return db_session.query(User).filter(User.email == "test-admin@example.com").one()


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


# --- /jobs/{id}/publish -- real LinkedIn posting vs manual fallback ---


def test_publish_linkedin_creates_real_post_when_connected(client, db_session, monkeypatch):
    admin = _admin_user(db_session)
    _connect_linkedin(db_session, admin, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    job = _make_job(db_session, status="ready_for_publishing")

    captured = {}

    def fake_create_post(access_token, *, member_urn, commentary):
        captured.update(access_token=access_token, member_urn=member_urn, commentary=commentary)
        return "urn:li:share:99999"

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", fake_create_post)

    response = client.post(f"/jobs/{job.id}/publish", json={"naukri": False, "linkedin": True, "career_portal": False})

    assert response.status_code == 200
    body = response.json()
    assert body["linkedin_post_urn"] == "urn:li:share:99999"
    assert body["posting_url_linkedin"] is None
    assert captured["member_urn"] == "urn:li:person:abc123"
    assert job.title in captured["commentary"]
    assert f"/careers/{job.id}" in captured["commentary"]

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "linkedin_post_created")
        .one_or_none()
    )
    assert entry is not None
    assert entry.details["post_urn"] == "urn:li:share:99999"


def test_publish_linkedin_real_post_ignores_manual_url(client, db_session, monkeypatch):
    # A real post has its own linkedin_post_urn -- a manually-pasted URL passed alongside
    # it would be redundant/stale, so it must be ignored when the real post succeeds.
    admin = _admin_user(db_session)
    _connect_linkedin(db_session, admin, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    job = _make_job(db_session, status="ready_for_publishing")

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", lambda *a, **k: "urn:li:share:1")

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": False,
            "linkedin": True,
            "career_portal": False,
            "posting_url_linkedin": "https://www.linkedin.com/manually-pasted",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["linkedin_post_urn"] == "urn:li:share:1"
    assert body["posting_url_linkedin"] is None


def test_publish_linkedin_falls_back_to_manual_url_when_post_fails(client, db_session, monkeypatch):
    admin = _admin_user(db_session)
    _connect_linkedin(db_session, admin, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    job = _make_job(db_session, status="ready_for_publishing")

    def fake_create_post(*a, **k):
        raise LinkedInError("LinkedIn API is down")

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", fake_create_post)

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": False,
            "linkedin": True,
            "career_portal": False,
            "posting_url_linkedin": "https://www.linkedin.com/manually-pasted",
        },
    )

    # Never blocks the main flow -- still a 200, just no real post.
    assert response.status_code == 200
    body = response.json()
    assert body["linkedin_post_urn"] is None
    assert body["posting_url_linkedin"] == "https://www.linkedin.com/manually-pasted"

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "linkedin_post_failed")
        .one_or_none()
    )
    assert entry is not None


def test_publish_linkedin_falls_back_when_token_expired(client, db_session, monkeypatch):
    admin = _admin_user(db_session)
    _connect_linkedin(db_session, admin, expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    job = _make_job(db_session, status="ready_for_publishing")

    def fail_if_called(*a, **k):
        raise AssertionError("must not attempt a post with a known-expired token")

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", fail_if_called)

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": False,
            "linkedin": True,
            "career_portal": False,
            "posting_url_linkedin": "https://www.linkedin.com/manually-pasted",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["linkedin_post_urn"] is None
    assert body["posting_url_linkedin"] == "https://www.linkedin.com/manually-pasted"

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "linkedin_post_skipped_expired_token")
        .one_or_none()
    )
    assert entry is not None


def test_publish_linkedin_not_connected_falls_back_to_manual_url(client, db_session, monkeypatch):
    job = _make_job(db_session, status="ready_for_publishing")

    def fail_if_called(*a, **k):
        raise AssertionError("must not attempt a post with no LinkedIn connection")

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", fail_if_called)

    response = client.post(
        f"/jobs/{job.id}/publish",
        json={
            "naukri": False,
            "linkedin": True,
            "career_portal": False,
            "posting_url_linkedin": "https://www.linkedin.com/manually-pasted",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["linkedin_post_urn"] is None
    assert body["posting_url_linkedin"] == "https://www.linkedin.com/manually-pasted"


def test_publish_linkedin_disabled_never_attempts_a_post(client, db_session, monkeypatch):
    admin = _admin_user(db_session)
    _connect_linkedin(db_session, admin, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    job = _make_job(db_session, status="ready_for_publishing")

    def fail_if_called(*a, **k):
        raise AssertionError("must not attempt a post when the linkedin toggle is off")

    monkeypatch.setattr("app.jobs.router.create_hiring_announcement_post", fail_if_called)

    response = client.post(f"/jobs/{job.id}/publish", json={"naukri": False, "linkedin": False, "career_portal": False})

    assert response.status_code == 200
    assert response.json()["linkedin_post_urn"] is None


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


# --- /jobs/field-suggestions ---


def test_field_suggestions_returns_distinct_deduped_sorted_values(client, db_session):
    before = client.get("/jobs/field-suggestions").json()

    _make_job(db_session, department="Engineering", location="Chennai", skills=["Python", "SQL"])
    _make_job(db_session, department="Engineering", location="Remote", skills=["Python", "AWS"])
    _make_job(db_session, department=None, location=None, skills=None)

    after = client.get("/jobs/field-suggestions").json()

    # Subset checks, not exact-set equality: this endpoint aggregates over every job
    # already in the shared database, which may already contain overlapping values
    # (e.g. "Python" from an unrelated real job) -- only assert what this test itself added.
    assert {"Engineering"}.issubset(set(after["departments"]))
    assert {"Chennai", "Remote"}.issubset(set(after["locations"]))
    assert {"Python", "SQL", "AWS"}.issubset(set(after["skills"]))
    # Deduped -- "Engineering" appears on two jobs above but only once in the response.
    assert after["departments"].count("Engineering") == 1
    assert after["departments"] == sorted(after["departments"])


def test_field_suggestions_route_not_shadowed_by_job_id_route(client):
    # /jobs/field-suggestions must resolve to this endpoint, not attempt to parse
    # "field-suggestions" as a job_id UUID on the /jobs/{job_id} route.
    response = client.get("/jobs/field-suggestions")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"departments", "locations", "skills"}


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
