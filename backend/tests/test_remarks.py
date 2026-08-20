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
    # No "experience_score"/"skill_match_pct"/"missing_skills"/"certificates_score" keys
    # -- match_resume no longer produces any of these; run_screening computes them
    # itself (see compute_experience_score/compute_skills_score/
    # compute_certificates_score), and these tests' jobs/candidates carry no
    # experience_min_years/max_years/total_experience_years, skill categories, or
    # preferred_certifications unless a test deliberately configures them, which all
    # three compute functions treat as "no requirement configured" -> a fixed 100 each.
    result = {
        "match_score": 80,
        "location_score": 80,
        "recommendation": "strong_fit",
    }
    result.update(overrides)
    return result


# --- describe_screening_audit_entry: pure function, no AI/DB access ---


def test_describe_scored_entry_with_no_missing_skills():
    details = {"recommendation": "strong_fit", "composite_score": 82.6, "missing_skills": []}
    assert screening_service.describe_screening_audit_entry("ai_screening_scored", details) == "Strong fit (score 83)"


def test_describe_scored_entry_with_missing_skills():
    # No "missing_required_skills"/"missing_preferred_skills" keys -- a historical entry
    # that predates the must-have/good-to-have categorization, rendered exactly as it
    # always was rather than inventing a severity split for data that never had one.
    details = {"recommendation": "possible_fit", "composite_score": 61.4, "missing_skills": ["Kubernetes", "AWS"]}
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Possible fit (score 61) -- missing Kubernetes, AWS"


def test_describe_scored_entry_distinguishes_required_from_preferred_gaps():
    details = {
        "recommendation": "possible_fit", "composite_score": 70.0,
        "missing_required_skills": ["Kubernetes"], "missing_preferred_skills": ["Docker"],
    }
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Possible fit (score 70) -- missing required: Kubernetes; missing preferred: Docker"


def test_describe_scored_entry_with_only_required_gaps():
    details = {
        "recommendation": "possible_fit", "composite_score": 70.0,
        "missing_required_skills": ["Kubernetes", "AWS"], "missing_preferred_skills": [],
    }
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Possible fit (score 70) -- missing required: Kubernetes, AWS"


def test_describe_scored_entry_with_only_preferred_gaps():
    details = {
        "recommendation": "strong_fit", "composite_score": 90.0,
        "missing_required_skills": [], "missing_preferred_skills": ["Docker"],
    }
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Strong fit (score 90) -- missing preferred: Docker"


def test_describe_scored_entry_with_categorization_present_but_no_gaps():
    details = {
        "recommendation": "strong_fit", "composite_score": 100.0,
        "missing_required_skills": [], "missing_preferred_skills": [],
    }
    text = screening_service.describe_screening_audit_entry("ai_screening_scored", details)
    assert text == "Strong fit (score 100)"


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


# --- describe_interview_readiness (Part F): pure function, no AI/DB access ---


def test_describe_interview_readiness_ready():
    details = {"composite_score": 84.0, "interview_ready": True}
    assert screening_service.describe_interview_readiness("ai_screening_scored", details) == "Interview ready (score 84)"


def test_describe_interview_readiness_below_threshold():
    details = {"composite_score": 52.0, "interview_ready": False}
    text = screening_service.describe_interview_readiness("ai_screening_scored", details)
    assert text == "Below interview threshold (score 52)"


def test_describe_interview_readiness_missing_key_predates_part_f():
    # A historical audit_log entry from before Part F existed -- interview_ready was never
    # evaluated for it, which must read as a plain "Screened," not a false "Below threshold."
    details = {"composite_score": 70.0, "recommendation": "possible_fit"}
    assert screening_service.describe_interview_readiness("ai_screening_scored", details) == "Screened (score 70)"


def test_describe_interview_readiness_missing_composite_score_omits_score_suffix():
    details = {"interview_ready": True}
    assert screening_service.describe_interview_readiness("ai_screening_scored", details) == "Interview ready"


def test_describe_interview_readiness_failed_entry_includes_the_error():
    details = {"error": "boom"}
    assert screening_service.describe_interview_readiness("ai_screening_failed", details) == "AI screening failed: boom"


# --- integration: Interview Readiness Remarks on the real List/export APIs (Part F) ---


def test_interview_remarks_derived_from_the_real_audit_log_entry(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    expected = screening_service.describe_interview_readiness(audit_entry.action, audit_entry.details)
    assert "interview_ready" in audit_entry.details  # Part F's own field, alongside "advanced"

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]
    assert row["interview_remarks"] == expected
    # remarks (Part C) and interview_remarks (Part F) are two different renderings of the
    # SAME entry -- distinct text, not a duplicate of each other.
    assert row["remarks"] != row["interview_remarks"]


def test_interview_remarks_appear_on_export_endpoint_too(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications/export", params={"application_ids": [str(application.id)]})
    assert response.status_code == 200
    assert response.json()[0]["interview_remarks"] is not None


def test_unscreened_application_has_null_interview_remarks(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    _make_application(db_session, job, candidate)

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    assert response.json()["items"][0]["interview_remarks"] is None


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
        match_score=90, location_score=90, recommendation="strong_fit",
    ))
    job = _make_job(db_session, technical_skills_good_to_have=["Docker"])
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
    # skill_match_pct = 100 - 20 (the one technical_skills_good_to_have entry, "Docker",
    # missed) = 80. Composite = (80_skills + 100_experience + 100_certificates + 90 + 90
    # -- the two AI-scored factors) / 5 = 92.
    assert row["remarks"] == "Strong fit (score 92) -- missing preferred: Docker"


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
        match_score=20, location_score=20, recommendation="weak_fit",
    ))
    screening_service.run_screening(db_session, application, job, candidate, "system")

    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=95, location_score=95, recommendation="strong_fit",
    ))
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]
    # (95 * 2 AI-scored factors + 100 + 100 + 100, the deterministic experience_score/
    # skill_match_pct/certificates_score for a job with no experience range, skill
    # categories, or preferred_certifications configured) / 5 = 98.
    assert row["remarks"] == "Strong fit (score 98)"


def test_remarks_appear_on_export_endpoint_too(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)
    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications/export", params={"application_ids": [str(application.id)]})
    assert response.status_code == 200
    # (80 * 2 AI-scored factors + 100 + 100 + 100, the deterministic experience_score/
    # skill_match_pct/certificates_score for a job with no experience range, skill
    # categories, or preferred_certifications configured) / 5 = 92.
    assert response.json()[0]["remarks"] == "Strong fit (score 92)"


def test_missing_skills_remain_in_remarks_alongside_the_new_composite_score_field(client, db_session, monkeypatch):
    # Regression test for the Match Score / Remarks score-mismatch fix: the List page's
    # Screening Score column now shows composite_score (not the raw match_score), but that
    # must not disturb Remarks' own missing-skills rendering, which is a completely separate
    # code path (describe_screening_audit_entry). match_score and composite_score are
    # asserted as genuinely distinct numbers here specifically so a future change that
    # collapses them back into one field wouldn't hide a regression in either.
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=70, location_score=100, recommendation="strong_fit",
    ))
    job = _make_job(
        db_session, technical_skills_must_have=["Kubernetes"], technical_skills_good_to_have=["Terraform"],
    )
    candidate = _make_candidate(db_session, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com")
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]

    # skill_match_pct = 100 - 50 (missed must-have "Kubernetes") - 20 (missed
    # good-to-have "Terraform") = 30. Composite = (30 + 100_experience + 70 + 100 +
    # 100) / 5 = 80.
    assert row["remarks"] == "Strong fit (score 80) -- missing required: Kubernetes; missing preferred: Terraform"
    assert row["match_score"] == 70
    assert row["composite_score"] == 80.0
    assert row["match_score"] != row["composite_score"]


def test_no_missing_skills_still_omits_the_suffix_alongside_the_new_composite_score_field(client, db_session, monkeypatch):
    # The other half of the same regression test: a genuine 100%-skill-match candidate must
    # still get no "-- missing ..." suffix, even though the row now also carries a distinct
    # composite_score field.
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result(
        match_score=88, location_score=90, recommendation="strong_fit",
    ))
    job = _make_job(db_session, technical_skills_must_have=["Python"])
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python"]}, email=f"remarks-{uuid.uuid4().hex[:8]}@example.com"
    )
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    response = client.get("/candidates/applications", params={"search": candidate.email, "page_size": 50})
    row = response.json()["items"][0]

    # The candidate's own skills fully cover technical_skills_must_have -> skill_match_pct
    # 100. (100_skills + 100_experience + 100_certificates + 88 + 90 -- the two
    # AI-scored factors) / 5 = 95.6.
    assert row["remarks"] == "Strong fit (score 96)"
    assert "missing" not in row["remarks"]
    assert row["composite_score"] == 95.6


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
        # (80 * 2 AI-scored factors + 100 + 100 + 100, the deterministic experience_score/
        # skill_match_pct/certificates_score for a job with no experience range, skill
        # categories, or preferred_certifications configured) / 5 = 92.
        assert matching[0]["remarks"] == "Strong fit (score 92)"
