import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.ai_services.jd_generator import JDGenerationError
from app.core.crypto import encrypt
from app.integrations.linkedin import LinkedInError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.reports import stats

_NOW = datetime.now(timezone.utc)


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, full_name="Jane Doe") -> Candidate:
    candidate = Candidate(full_name=full_name)
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


def _make_audit_entry(db_session, entity_type, entity_id, action, actor="system", details=None, created_at=None):
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=details,
        created_at=created_at or _NOW,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _months_ago(n: int, day: int = 10) -> datetime:
    month_start_boundary = stats.shift_months(stats.month_start(_NOW), -n)
    return month_start_boundary + timedelta(days=day - 1, hours=12)


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


def test_generate_job_description_passes_full_role_inputs(client, db_session, monkeypatch):
    # Requirements/salary/benefits/additional-notes are collected in earlier wizard steps
    # now (see CreateJobWizard's reordered STEPS) specifically so they're available by
    # the time JD generation runs -- this proves the router actually forwards all of it,
    # not just title/department/location/experience_min_years/experience_max_years as
    # before that reorder.
    captured = {}

    def fake_generate_jd(inputs):
        captured.update(inputs)
        return {
            "title": "Backend Engineer",
            "summary": "x",
            "responsibilities": ["x"],
            "required_skills": ["x"],
            "nice_to_have": [],
            "experience_required": "x",
            "compensation_and_benefits": "Salary: 1500000-2200000. Benefits: Health insurance, WFH stipend.",
            "additional_notes_section": "Team is fully remote-first",
            "education_requirement": "Bachelor's degree in Computer Science or related field",
            "preferred_certifications_section": "PMP, AWS Certified Solutions Architect",
        }

    monkeypatch.setattr("app.jobs.router.generate_jd", fake_generate_jd)

    job = _make_job(
        db_session,
        department="Engineering",
        location="Hyderabad",
        experience_min_years=5,
        experience_max_years=8,
        technical_skills_must_have=["Python"],
        technical_skills_good_to_have=["FastAPI"],
        soft_skills_must_have=["Communication"],
        soft_skills_good_to_have=["Teamwork"],
        salary_band_min=1500000,
        salary_band_max=2200000,
        benefits="Health insurance, WFH stipend",
        additional_notes="Team is fully remote-first",
        key_responsibilities="Own backend services end-to-end and mentor junior engineers.",
        education_degree_level="Bachelor's",
        education_field="Computer Science",
        preferred_certifications=["PMP", "AWS Certified Solutions Architect"],
    )

    response = client.post(f"/jobs/{job.id}/generate-jd")

    assert response.status_code == 200
    assert captured["experience_min_years"] == 5
    assert captured["experience_max_years"] == 8
    assert captured["technical_skills_must_have"] == ["Python"]
    assert captured["technical_skills_good_to_have"] == ["FastAPI"]
    assert captured["soft_skills_must_have"] == ["Communication"]
    assert captured["soft_skills_good_to_have"] == ["Teamwork"]
    assert captured["salary_band_min"] == 1500000
    assert captured["salary_band_max"] == 2200000
    assert captured["benefits"] == "Health insurance, WFH stipend"
    assert captured["additional_notes"] == "Team is fully remote-first"
    assert captured["key_responsibilities"] == "Own backend services end-to-end and mentor junior engineers."
    assert captured["education_degree_level"] == "Bachelor's"
    assert captured["education_field"] == "Computer Science"
    assert captured["preferred_certifications"] == ["PMP", "AWS Certified Solutions Architect"]

    # The AI's compensation/notes output must actually make it into the rendered
    # jd_text -- passing the inputs to the model isn't enough if the render step
    # drops them, which is exactly what happened before these output fields were added.
    jd_text = response.json()["jd_text"]
    assert "Compensation & Benefits:" in jd_text
    assert "Health insurance, WFH stipend" in jd_text
    assert "Additional Notes:" in jd_text
    assert "Team is fully remote-first" in jd_text
    assert "Education:" in jd_text
    assert "Bachelor's degree in Computer Science or related field" in jd_text
    assert "Preferred Certifications:" in jd_text
    assert "PMP, AWS Certified Solutions Architect" in jd_text


def test_generate_job_description_omits_compensation_section_when_not_provided(
    client, db_session, monkeypatch
):
    # When the model has nothing to say (no salary/benefits/notes were input), it
    # returns null for these fields per the system prompt's "don't fabricate" rule --
    # the renderer must skip the section entirely rather than printing an empty header.
    def fake_generate_jd(inputs):
        return {
            "title": "Backend Engineer",
            "summary": "x",
            "responsibilities": ["x"],
            "required_skills": ["x"],
            "nice_to_have": [],
            "experience_required": "x",
            "compensation_and_benefits": None,
            "additional_notes_section": None,
        }

    monkeypatch.setattr("app.jobs.router.generate_jd", fake_generate_jd)

    job = _make_job(db_session)
    response = client.post(f"/jobs/{job.id}/generate-jd")

    assert response.status_code == 200
    jd_text = response.json()["jd_text"]
    assert "Compensation & Benefits:" not in jd_text
    assert "Additional Notes:" not in jd_text
    assert "Education:" not in jd_text
    assert "Preferred Certifications:" not in jd_text


def test_generate_job_description_not_found(client):
    response = client.post(f"/jobs/{uuid.uuid4()}/generate-jd")
    assert response.status_code == 404


# --- DELETE /jobs/{id} ---


def test_delete_draft_job_succeeds(client, db_session):
    job = _make_job(db_session, status="draft")
    job_id = job.id

    response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 204
    assert db_session.get(JobRole, job_id) is None


def test_delete_ready_for_publishing_job_succeeds(client, db_session):
    job = _make_job(db_session, status="ready_for_publishing")
    job_id = job.id

    response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 204
    assert db_session.get(JobRole, job_id) is None


def test_delete_published_job_blocked(client, db_session):
    job = _make_job(db_session, status="published")

    response = client.delete(f"/jobs/{job.id}")

    assert response.status_code == 400
    assert db_session.get(JobRole, job.id) is not None


def test_delete_on_hold_job_blocked(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.delete(f"/jobs/{job.id}")

    assert response.status_code == 400
    assert db_session.get(JobRole, job.id) is not None


def test_delete_closed_job_blocked(client, db_session):
    job = _make_job(db_session, status="closed")

    response = client.delete(f"/jobs/{job.id}")

    assert response.status_code == 400
    assert db_session.get(JobRole, job.id) is not None


def test_delete_draft_job_with_applications_blocked(client, db_session):
    # A draft/ready_for_publishing job with real applications (e.g. created via direct
    # API use before ever being published) must not be deletable -- that would silently
    # destroy application data rather than just an empty, never-used job posting.
    job = _make_job(db_session, status="draft")
    candidate = _make_candidate(db_session)
    _make_application(db_session, job, candidate)

    response = client.delete(f"/jobs/{job.id}")

    assert response.status_code == 400
    assert db_session.get(JobRole, job.id) is not None


def test_delete_job_not_found(client):
    response = client.delete(f"/jobs/{uuid.uuid4()}")
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

    # Skills spread across categories and jobs -- proves the suggestions endpoint
    # aggregates across all 4 categorized skill columns, not just one.
    _make_job(
        db_session, department="Engineering", location="Chennai",
        technical_skills_must_have=["Python"], technical_skills_good_to_have=["SQL"],
    )
    _make_job(
        db_session, department="Engineering", location="Remote",
        soft_skills_must_have=["AWS"],
    )
    _make_job(db_session, department=None, location=None, preferred_certifications=["PMP", "CPA"])

    after = client.get("/jobs/field-suggestions").json()

    # Subset checks, not exact-set equality: this endpoint aggregates over every job
    # already in the shared database, which may already contain overlapping values
    # (e.g. "Python" from an unrelated real job) -- only assert what this test itself added.
    assert {"Engineering"}.issubset(set(after["departments"]))
    assert {"Chennai", "Remote"}.issubset(set(after["locations"]))
    assert {"Python", "SQL", "AWS"}.issubset(set(after["skills"]))
    assert {"PMP", "CPA"}.issubset(set(after["certifications"]))
    # Deduped -- "Engineering" appears on two jobs above but only once in the response.
    assert after["departments"].count("Engineering") == 1
    assert after["departments"] == sorted(after["departments"])


def test_field_suggestions_route_not_shadowed_by_job_id_route(client):
    # /jobs/field-suggestions must resolve to this endpoint, not attempt to parse
    # "field-suggestions" as a job_id UUID on the /jobs/{job_id} route.
    response = client.get("/jobs/field-suggestions")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"departments", "locations", "skills", "certifications"}


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


# --- on_hold status transitions -------------------------------------------------


def test_hold_job_from_published_succeeds(client, db_session):
    job = _make_job(db_session, status="published")

    response = client.post(f"/jobs/{job.id}/hold")

    assert response.status_code == 200
    assert response.json()["status"] == "on_hold"
    db_session.refresh(job)
    assert job.status == "on_hold"


def test_hold_job_logs_audit_entry(client, db_session):
    job = _make_job(db_session, status="published")

    client.post(f"/jobs/{job.id}/hold")

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "job_put_on_hold")
        .one()
    )
    assert entry.details["previous_status"] == "published"
    assert entry.details["new_status"] == "on_hold"


def test_hold_job_from_non_published_status_rejected(client, db_session):
    job = _make_job(db_session, status="draft")

    response = client.post(f"/jobs/{job.id}/hold")

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "draft"


def test_resume_job_from_on_hold_succeeds(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.post(f"/jobs/{job.id}/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    db_session.refresh(job)
    assert job.status == "published"


def test_resume_job_logs_audit_entry(client, db_session):
    job = _make_job(db_session, status="on_hold")

    client.post(f"/jobs/{job.id}/resume")

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "job_resumed_from_hold")
        .one()
    )
    assert entry.details["previous_status"] == "on_hold"
    assert entry.details["new_status"] == "published"


def test_resume_job_from_non_on_hold_status_rejected(client, db_session):
    job = _make_job(db_session, status="published")

    response = client.post(f"/jobs/{job.id}/resume")

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "published"


def test_patch_status_on_hold_to_closed_succeeds(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.patch(f"/jobs/{job.id}", json={"status": "closed"})

    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_patch_status_draft_to_on_hold_rejected(client, db_session):
    job = _make_job(db_session, status="draft")

    response = client.patch(f"/jobs/{job.id}", json={"status": "on_hold"})

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "draft"


def test_patch_status_on_hold_to_draft_rejected(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.patch(f"/jobs/{job.id}", json={"status": "draft"})

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "on_hold"


def test_patch_status_on_hold_to_ready_for_publishing_rejected(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.patch(f"/jobs/{job.id}", json={"status": "ready_for_publishing"})

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "on_hold"


def test_patch_status_transitions_not_touching_on_hold_remain_unrestricted(client, db_session):
    # Pre-existing behavior, not part of this change -- draft straight to closed (skipping
    # every intermediate status) was already unvalidated before on_hold existed, and stays
    # that way; only transitions that touch on_hold are newly guarded.
    job = _make_job(db_session, status="draft")

    response = client.patch(f"/jobs/{job.id}", json={"status": "closed"})

    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_generate_jd_on_held_job_rejected(client, db_session, monkeypatch):
    job = _make_job(db_session, status="on_hold")

    response = client.post(f"/jobs/{job.id}/generate-jd")

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "on_hold"
    assert job.jd_text is None


def test_publish_on_held_job_rejected(client, db_session):
    job = _make_job(db_session, status="on_hold")

    response = client.post(
        f"/jobs/{job.id}/publish", json={"naukri": False, "linkedin": False, "career_portal": True}
    )

    assert response.status_code == 400
    db_session.refresh(job)
    assert job.status == "on_hold"


# --- job_type ---------------------------------------------------------------------


def test_create_job_defaults_job_type_to_full_time(client):
    response = client.post("/jobs", json={"title": "Default Job Type Role"})

    assert response.status_code == 201
    assert response.json()["job_type"] == "Full-time"


def test_create_job_with_explicit_job_type(client):
    response = client.post("/jobs", json={"title": "Contract Role", "job_type": "Contract"})

    assert response.status_code == 201
    assert response.json()["job_type"] == "Contract"


def test_update_job_type(client, db_session):
    job = _make_job(db_session)

    response = client.patch(f"/jobs/{job.id}", json={"job_type": "Part-time"})

    assert response.status_code == 200
    assert response.json()["job_type"] == "Part-time"


def test_existing_row_backfilled_to_full_time_job_type(db_session):
    # Built directly from the model (bypassing the API/schema default entirely) to prove
    # the *migration's* DB-level server_default is what backfills pre-existing rows --
    # not just the Pydantic schema default, which a raw model instantiation skips.
    job = JobRole(title="Pre-migration Role")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.job_type == "Full-time"


# --- experience_min_years/experience_max_years validation ---------------------------


def test_create_job_with_valid_experience_range(client):
    response = client.post(
        "/jobs", json={"title": "Ranged Role", "experience_min_years": 3, "experience_max_years": 5}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["experience_min_years"] == 3
    assert body["experience_max_years"] == 5


def test_create_job_with_open_ended_experience_min_only(client):
    # max left blank -- "5+ years."
    response = client.post("/jobs", json={"title": "Open Ended Role", "experience_min_years": 5})
    assert response.status_code == 201
    body = response.json()
    assert body["experience_min_years"] == 5
    assert body["experience_max_years"] is None


def test_create_job_rejects_negative_experience_min(client):
    response = client.post("/jobs", json={"title": "Bad Role", "experience_min_years": -1})
    assert response.status_code == 422


def test_create_job_rejects_negative_experience_max(client):
    response = client.post("/jobs", json={"title": "Bad Role", "experience_max_years": -1})
    assert response.status_code == 422


def test_create_job_rejects_max_below_min(client):
    response = client.post(
        "/jobs", json={"title": "Bad Range Role", "experience_min_years": 5, "experience_max_years": 3}
    )
    assert response.status_code == 422


def test_create_job_allows_max_equal_to_min(client):
    response = client.post(
        "/jobs", json={"title": "Exact Role", "experience_min_years": 4, "experience_max_years": 4}
    )
    assert response.status_code == 201


def test_update_job_rejects_max_below_min(client, db_session):
    job = _make_job(db_session, experience_min_years=3, experience_max_years=6)
    response = client.patch(
        f"/jobs/{job.id}", json={"experience_min_years": 5, "experience_max_years": 2}
    )
    assert response.status_code == 422


def test_update_job_with_valid_experience_range(client, db_session):
    job = _make_job(db_session)
    response = client.patch(
        f"/jobs/{job.id}", json={"experience_min_years": 2, "experience_max_years": 4}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["experience_min_years"] == 2
    assert body["experience_max_years"] == 4


# --- 4 categorized skill lists: validation ---------------------------------------


def test_create_job_with_all_4_skill_categories(client):
    response = client.post(
        "/jobs",
        json={
            "title": "Categorized Skills Role",
            "technical_skills_must_have": ["Python"],
            "technical_skills_good_to_have": ["Kubernetes"],
            "soft_skills_must_have": ["Communication"],
            "soft_skills_good_to_have": ["Empathy"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["technical_skills_must_have"] == ["Python"]
    assert body["technical_skills_good_to_have"] == ["Kubernetes"]
    assert body["soft_skills_must_have"] == ["Communication"]
    assert body["soft_skills_good_to_have"] == ["Empathy"]


def test_create_job_rejects_a_skill_in_two_categories(client):
    response = client.post(
        "/jobs",
        json={
            "title": "Conflicting Skills Role",
            "technical_skills_must_have": ["Python"],
            "technical_skills_good_to_have": ["Python"],
        },
    )
    assert response.status_code == 422


def test_create_job_rejects_a_skill_in_two_categories_case_and_whitespace_insensitively(client):
    response = client.post(
        "/jobs",
        json={
            "title": "Conflicting Skills Role",
            "technical_skills_must_have": ["Python"],
            "soft_skills_good_to_have": ["  PYTHON  "],
        },
    )
    assert response.status_code == 422


def test_create_job_allows_the_same_skill_repeated_within_one_category(client):
    # A duplicate within the SAME category is not a contradiction (just redundant) --
    # only a skill split across two different categories is rejected.
    response = client.post(
        "/jobs",
        json={"title": "Redundant Skill Role", "technical_skills_must_have": ["Python", "Python"]},
    )
    assert response.status_code == 201


def test_update_job_rejects_a_skill_in_two_categories(client, db_session):
    job = _make_job(db_session)
    response = client.patch(
        f"/jobs/{job.id}",
        json={"technical_skills_must_have": ["Python"], "technical_skills_good_to_have": ["Python"]},
    )
    assert response.status_code == 422


# --- key_responsibilities / education / preferred_certifications: validation ------


def test_create_job_with_responsibilities_education_and_certifications(client):
    response = client.post(
        "/jobs",
        json={
            "title": "Senior Backend Engineer",
            "key_responsibilities": "Own backend services end-to-end and mentor junior engineers.",
            "education_degree_level": "Bachelor's",
            "education_field": "Computer Science",
            "preferred_certifications": ["PMP", "AWS Certified Solutions Architect"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key_responsibilities"] == "Own backend services end-to-end and mentor junior engineers."
    assert body["education_degree_level"] == "Bachelor's"
    assert body["education_field"] == "Computer Science"
    assert body["preferred_certifications"] == ["PMP", "AWS Certified Solutions Architect"]


def test_create_job_without_responsibilities_education_or_certifications_defaults_to_null(client):
    # All three are optional -- a job with none of them configured must not error and
    # must not silently default to an empty list/string that would then render oddly.
    response = client.post("/jobs", json={"title": "Bare Bones Role"})
    assert response.status_code == 201
    body = response.json()
    assert body["key_responsibilities"] is None
    assert body["education_degree_level"] is None
    assert body["education_field"] is None
    assert body["preferred_certifications"] is None


def test_update_job_sets_education_and_certifications(client, db_session):
    job = _make_job(db_session)
    response = client.patch(
        f"/jobs/{job.id}",
        json={
            "education_degree_level": "Master's",
            "education_field": "Data Science",
            "preferred_certifications": ["CPA"],
            "key_responsibilities": "Lead the analytics roadmap.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["education_degree_level"] == "Master's"
    assert body["education_field"] == "Data Science"
    assert body["preferred_certifications"] == ["CPA"]
    assert body["key_responsibilities"] == "Lead the analytics roadmap."


def test_education_degree_level_rejects_a_value_outside_the_allowed_list_at_the_db_level(db_session):
    # No Pydantic-level enum validation for education_degree_level, same convention as
    # job_type -- the DB CheckConstraint (job_role.py's EDUCATION_DEGREE_LEVELS) is the
    # one source of truth, so this is exercised directly against the DB session rather
    # than through the API.
    from sqlalchemy.exc import IntegrityError

    job = JobRole(title="Bad Degree Role", education_degree_level="Associate's")
    db_session.add(job)
    with pytest.raises(IntegrityError):
        db_session.commit()


# --- per-job table stats: application_count / applications_pct_change / avg_time_to_hire_days


def test_list_jobs_includes_application_count(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_application(db_session, job, candidate)
    _make_application(db_session, job, candidate)

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["application_count"] == 2


def test_list_jobs_application_trend_compares_to_last_month(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    # One application last month (the "before" baseline this job's trend compares
    # against), one more this month (on top of it).
    _make_application(db_session, job, candidate, created_at=_months_ago(1))
    _make_application(db_session, job, candidate, created_at=_NOW)

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["application_count"] == 2
    # current=2, compare(as of last month-end)=1 -> +100%
    assert row["applications_pct_change"] == 100.0


def test_list_jobs_application_trend_null_when_nothing_to_compare(client, db_session):
    job = _make_job(db_session)

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["application_count"] == 0
    # 0 vs 0 -- a real, computed "no change", not "nothing to compare".
    assert row["applications_pct_change"] == 0.0


def test_list_jobs_avg_time_to_hire_for_completed_hires(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    app_a = _make_application(db_session, job, candidate, created_at=_NOW - timedelta(days=20))
    app_b = _make_application(db_session, job, candidate, created_at=_NOW - timedelta(days=40))
    _make_audit_entry(db_session, "application", app_a.id, "onboarding_completed", created_at=_NOW)
    _make_audit_entry(db_session, "application", app_b.id, "onboarding_completed", created_at=_NOW)

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["avg_time_to_hire_days"] == 30.0


def test_list_jobs_avg_time_to_hire_not_scoped_to_current_month(client, db_session):
    # Unlike the dashboard-wide Avg Time to Hire (scoped to this calendar month), the
    # per-job column is a real all-time average -- a hire completed months ago must
    # still count, not disappear the moment the calendar month rolls over.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, created_at=_months_ago(6) - timedelta(days=25))
    _make_audit_entry(
        db_session, "application", application.id, "onboarding_completed", created_at=_months_ago(6)
    )

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["avg_time_to_hire_days"] == 25.0


def test_list_jobs_avg_time_to_hire_null_when_no_completed_hires(client, db_session):
    job = _make_job(db_session)
    _make_application(db_session, job, _make_candidate(db_session), status="screened")

    body = client.get("/jobs").json()
    row = next(j for j in body if j["id"] == str(job.id))

    assert row["avg_time_to_hire_days"] is None


def test_list_jobs_table_stats_are_scoped_per_job_not_global(client, db_session):
    # Two jobs, each with their own application -- job A's count must not leak into job B.
    job_a = _make_job(db_session)
    job_b = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_application(db_session, job_a, candidate)
    _make_application(db_session, job_a, candidate)
    _make_application(db_session, job_b, candidate)

    body = client.get("/jobs").json()
    row_a = next(j for j in body if j["id"] == str(job_a.id))
    row_b = next(j for j in body if j["id"] == str(job_b.id))

    assert row_a["application_count"] == 2
    assert row_b["application_count"] == 1
