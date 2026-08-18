import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.screening import service as screening_service


def _make_job(db_session, jd_text="Backend role needing Python.", **kwargs) -> JobRole:
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


def _make_application(db_session, job, candidate, status="received", **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


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


# --- describe_screening_audit_entry: pure function, no AI/DB access ---


def test_describe_scored_entry_with_no_missing_skills():
    details = {"recommendation": "strong_fit", "composite_score": 82.6, "missing_skills": []}
    assert screening_service.describe_screening_audit_entry("ai_screening_scored", details) == "Strong fit (score 83)"


def test_describe_scored_entry_with_missing_skills():
    details = {"recommendation": "possible_fit", "composite_score": 61.4, "missing_skills": ["Kubernetes", "AWS"]}
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Possible fit (score 61) -- missing Kubernetes, AWS"


def test_describe_scored_entry_weak_fit_label():
    details = {"recommendation": "weak_fit", "composite_score": 22.0, "missing_skills": []}
    assert screening_service.describe_screening_audit_entry("ai_screening_scored", details) == "Weak fit (score 22)"


def test_describe_scored_entry_unknown_recommendation_falls_back_to_screened():
    details = {"recommendation": "something_new", "composite_score": 50.0, "missing_skills": []}
    assert screening_service.describe_screening_audit_entry("ai_screening_scored", details) == "Screened (score 50)"


def test_describe_scored_entry_missing_composite_score_omits_score_suffix():
    details = {"recommendation": "strong_fit", "missing_skills": []}
    assert screening_service.describe_screening_audit_entry("ai_screening_scored", details) == "Strong fit"


def test_describe_failed_entry_includes_the_error():
    details = {"error": "Failed to match resume against job description: timeout"}
    text = screening_service.describe_screening_audit_entry("ai_screening_failed", details)
    assert text == "AI screening failed: Failed to match resume against job description: timeout"


def test_describe_failed_entry_missing_error_key_still_produces_text():
    assert screening_service.describe_screening_audit_entry("ai_screening_failed", {}) == "AI screening failed: unknown error"


# --- integration: Remarks on the real List/export/dashboard APIs, derived from real audit_log rows ---


def test_unscreened_application_has_null_remarks(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    _make_application(db_session, job, candidate)

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})

    assert response.status_code == 200
    assert response.json()["items"][0]["remarks"] is None


def test_scored_application_shows_remarks_derived_from_the_real_audit_log_entry(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=90, skill_match_pct=90, experience_score=90, location_score=90, certificates_score=90,
        missing_skills=["Docker"], recommendation="strong_fit",
    ))
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    # The Remarks text must be exactly describe_screening_audit_entry applied to the real
    # audit_log row run_screening just wrote -- not some independently-computed string.
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    expected = screening_service.describe_screening_audit_entry(audit_entry.action, audit_entry.details)

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]
    assert row["remarks"] == expected
    assert row["remarks"] == "Strong fit (score 90) -- missing Docker"


def test_failed_screening_shows_remarks_even_though_application_stays_received(client, db_session, monkeypatch):
    from app.ai_services.resume_matcher import ResumeMatchError

    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session)
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python"]}, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com"
    )
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)
    assert outcome is None  # swallowed, per Part A's existing contract

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]
    assert row["status"] == "received"
    assert row["remarks"] == "AI screening failed: boom"


def test_remarks_reflects_the_latest_screening_entry_not_the_first(client, db_session, monkeypatch):
    # Re-screening (the manual "Screen Candidate" button has no eligibility gate, unlike
    # the automatic hooks) must update Remarks to the newest result, not keep showing a
    # stale first pass.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=20, skill_match_pct=20, experience_score=20, location_score=20, certificates_score=20,
        recommendation="weak_fit",
    ))
    screening_service.run_screening(db_session, application, job, candidate, "system")

    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=95, skill_match_pct=95, experience_score=95, location_score=95, certificates_score=95,
        recommendation="strong_fit",
    ))
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]
    assert row["remarks"] == "Strong fit (score 95)"


def test_remarks_appear_on_export_endpoint_too(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications/export", params={"application_ids": [str(application.id)]})
    assert response.status_code == 200
    assert response.json()[0]["remarks"] == "Strong fit (score 80)"


def test_missing_skills_remain_in_remarks_alongside_the_new_composite_score_field(client, db_session, monkeypatch):
    # Regression test for the Match Score / Remarks score-mismatch fix: the List page's
    # Screening Score column now shows composite_score (not the raw match_score), but that
    # must not disturb Remarks' own missing-skills rendering, which is a completely separate
    # code path (describe_screening_audit_entry). match_score and composite_score are
    # asserted as genuinely distinct numbers here specifically so a future change that
    # collapses them back into one field wouldn't hide a regression in either.
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=70, skill_match_pct=100, experience_score=100, location_score=100, certificates_score=100,
        missing_skills=["Kubernetes", "Terraform"], recommendation="strong_fit",
    ))
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]

    assert row["remarks"] == "Strong fit (score 94) -- missing Kubernetes, Terraform"
    assert row["match_score"] == 70
    assert row["composite_score"] == 94.0
    assert row["match_score"] != row["composite_score"]


def test_no_missing_skills_still_omits_the_suffix_alongside_the_new_composite_score_field(client, db_session, monkeypatch):
    # The other half of the same regression test: a genuine 100%-skill-match candidate must
    # still get no "-- missing ..." suffix, even though the row now also carries a distinct
    # composite_score field.
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=88, skill_match_pct=100, experience_score=90, location_score=90, certificates_score=90,
        missing_skills=[], recommendation="strong_fit",
    ))
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]

    assert row["remarks"] == "Strong fit (score 92)"
    assert "missing" not in row["remarks"]
    assert row["composite_score"] == 91.6


def test_remarks_appear_on_dashboard_recent_candidates(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/reports/candidates-dashboard-stats")
    assert response.status_code == 200
    matching = [r for r in response.json()["recent_candidates"] if r["application_id"] == str(application.id)]
    # recent_candidates is capped to the latest 8 applications system-wide -- may have
    # scrolled off in a busy shared dev DB; only assert the shape when actually present.
    if matching:
        assert matching[0]["remarks"] == "Strong fit (score 80)"
