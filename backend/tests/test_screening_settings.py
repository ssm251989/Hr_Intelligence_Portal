from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.screening import service as screening_service

FAKE_MATCH_RESULT_70 = {
    "match_score": 70,
    "skill_match_pct": 70,
    "experience_score": 70,
    "location_score": 70,
    "certificates_score": 70,
    "missing_skills": [],
    "recommendation": "possible_fit",
}

FAKE_MATCH_RESULT_95 = {
    "match_score": 95,
    "skill_match_pct": 95,
    "experience_score": 95,
    "location_score": 95,
    "certificates_score": 95,
    "missing_skills": [],
    "recommendation": "strong_fit",
}


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


def _make_application(db_session, job, candidate, **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


# --- GET/PUT /screening/settings ---


def test_get_settings_returns_a_valid_singleton_row(client):
    # Deliberately not asserting the migration-seeded 60/100 default: this is a real,
    # admin-editable singleton row in the shared dev database, so by the time this test
    # runs it may already reflect a value some earlier real usage (manual or automated)
    # saved -- see test_put_settings_updates_the_singleton_row below for the "GET reflects
    # exactly what PUT wrote" contract. All this checks is the general shape/invariant that
    # always holds regardless of the current real value.
    response = client.get("/screening/settings")
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["dashboard_min_score"] <= 100
    assert 0 <= body["dashboard_max_score"] <= 100
    assert body["dashboard_min_score"] <= body["dashboard_max_score"]


def test_put_settings_updates_the_singleton_row(client):
    response = client.put("/screening/settings", json={"dashboard_min_score": 45, "dashboard_max_score": 90})
    assert response.status_code == 200
    assert response.json()["dashboard_min_score"] == 45
    assert response.json()["dashboard_max_score"] == 90

    # Reading it back confirms the singleton row itself was updated, not just echoed.
    response = client.get("/screening/settings")
    assert response.json()["dashboard_min_score"] == 45
    assert response.json()["dashboard_max_score"] == 90


def test_put_settings_rejects_min_above_max(client):
    response = client.put("/screening/settings", json={"dashboard_min_score": 90, "dashboard_max_score": 45})
    assert response.status_code == 422


def test_put_settings_rejects_out_of_range_values(client):
    response = client.put("/screening/settings", json={"dashboard_min_score": -5, "dashboard_max_score": 100})
    assert response.status_code == 422


def test_get_settings_requires_auth(anonymous_client):
    response = anonymous_client.get("/screening/settings")
    assert response.status_code == 401


# --- Part F: the separate interview_min/max_score pair, partial-update semantics ---


def test_get_settings_includes_the_interview_threshold_pair(client):
    response = client.get("/screening/settings")
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["interview_min_score"] <= 100
    assert 0 <= body["interview_max_score"] <= 100
    assert body["interview_min_score"] <= body["interview_max_score"]


def test_put_settings_interview_pair_only_leaves_dashboard_pair_untouched(client):
    # Establish a known dashboard pair first, then update ONLY the interview pair --
    # dashboard_min/max_score must come back completely unchanged.
    client.put("/screening/settings", json={"dashboard_min_score": 55, "dashboard_max_score": 95})

    response = client.put("/screening/settings", json={"interview_min_score": 80, "interview_max_score": 97})
    assert response.status_code == 200
    body = response.json()
    assert body["interview_min_score"] == 80
    assert body["interview_max_score"] == 97
    assert body["dashboard_min_score"] == 55
    assert body["dashboard_max_score"] == 95


def test_put_settings_dashboard_pair_only_leaves_interview_pair_untouched(client):
    # The inverse: establish a known interview pair, then update ONLY the dashboard pair.
    client.put("/screening/settings", json={"interview_min_score": 82, "interview_max_score": 99})

    response = client.put("/screening/settings", json={"dashboard_min_score": 40, "dashboard_max_score": 85})
    assert response.status_code == 200
    body = response.json()
    assert body["dashboard_min_score"] == 40
    assert body["dashboard_max_score"] == 85
    assert body["interview_min_score"] == 82
    assert body["interview_max_score"] == 99


def test_put_settings_rejects_interview_min_above_max(client):
    response = client.put("/screening/settings", json={"interview_min_score": 90, "interview_max_score": 45})
    assert response.status_code == 422


def test_put_settings_rejects_interview_min_without_max(client):
    response = client.put("/screening/settings", json={"interview_min_score": 80})
    assert response.status_code == 422


def test_put_settings_rejects_empty_payload(client):
    response = client.put("/screening/settings", json={})
    assert response.status_code == 422


# --- Functional: changing the INTERVIEW threshold changes Interview Readiness Remarks for a NEW upload ---


def test_changing_interview_threshold_changes_interview_remarks_for_a_new_upload(client, db_session, monkeypatch):
    # Fixed AI result: composite exactly 70.0, same trick as the dashboard-threshold test
    # above -- but this time it's the SEPARATE interview_min_score pair being exercised, and
    # the dashboard pair is pinned so both applications land in the same 'screened' status
    # regardless (isolating this test to interview_remarks, not a dashboard-threshold effect).
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: dict(FAKE_MATCH_RESULT_70))
    client.put("/screening/settings", json={"dashboard_min_score": 0, "dashboard_max_score": 100})

    job = _make_job(db_session)

    client.put("/screening/settings", json={"interview_min_score": 80, "interview_max_score": 100})
    candidate_a = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application_a = _make_application(db_session, job, candidate_a)
    screening_service.attempt_auto_screen(db_session, application_a)

    row_a = next(
        i for i in client.get(
            "/candidates/applications", params={"job_role_id": str(job.id), "page_size": 50}
        ).json()["items"]
        if i["application_id"] == str(application_a.id)
    )
    assert row_a["interview_remarks"] == "Below interview threshold (score 70)"  # 70 < 80

    client.put("/screening/settings", json={"interview_min_score": 50, "interview_max_score": 100})
    candidate_b = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application_b = _make_application(db_session, job, candidate_b)
    screening_service.attempt_auto_screen(db_session, application_b)

    row_b = next(
        i for i in client.get(
            "/candidates/applications", params={"job_role_id": str(job.id), "page_size": 50}
        ).json()["items"]
        if i["application_id"] == str(application_b.id)
    )
    assert row_b["interview_remarks"] == "Interview ready (score 70)"  # 70 >= 50


# --- Functional: changing the threshold changes auto-advance for a NEW upload ---


def test_changing_threshold_changes_auto_advance_for_a_new_upload(client, db_session, monkeypatch):
    # Fixed AI result: skills=experience=location=certs=match=70 -> composite exactly 70.0,
    # regardless of which candidate/application it's run against.
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: dict(FAKE_MATCH_RESULT_70))

    job = _make_job(db_session)

    # Raise the threshold above what a new upload will score -- attempt_auto_screen is
    # exactly what the resume-parse/application-creation hooks call for a brand new upload.
    response = client.put("/screening/settings", json={"dashboard_min_score": 80, "dashboard_max_score": 100})
    assert response.status_code == 200

    candidate_a = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application_a = _make_application(db_session, job, candidate_a)
    screening_service.attempt_auto_screen(db_session, application_a)
    db_session.refresh(application_a)
    assert application_a.composite_score == 70.0
    assert application_a.status == "received"  # 70 < 80 -- never auto-advances

    # Lower the threshold below that same score -- a genuinely new upload (fresh candidate,
    # fresh application) now clears it.
    response = client.put("/screening/settings", json={"dashboard_min_score": 50, "dashboard_max_score": 100})
    assert response.status_code == 200

    candidate_b = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    application_b = _make_application(db_session, job, candidate_b)
    screening_service.attempt_auto_screen(db_session, application_b)
    db_session.refresh(application_b)
    assert application_b.composite_score == 70.0
    assert application_b.status == "screened"  # 70 >= 50 -- auto-advances


# --- Re-evaluate All (Part D) ---


def test_re_evaluate_all_updates_received_and_screened_but_skips_already_decided_and_on_hold(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: dict(FAKE_MATCH_RESULT_95))
    job = _make_job(db_session)

    received_candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    received_app = _make_application(db_session, job, received_candidate, status="received")

    # Already screened by an earlier, stalers run -- still screening's own territory, so a
    # re-evaluate should refresh its score even though status doesn't need to change.
    screened_candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    screened_app = _make_application(
        db_session, job, screened_candidate, status="screened", match_score=10, composite_score=10
    )

    # A human already decided on this one -- must be left completely untouched.
    decided_candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    decided_app = _make_application(
        db_session, job, decided_candidate, status="hr_selected", match_score=99, composite_score=99
    )

    # Deliberately paused -- must also be left untouched, even though it was 'received'
    # before being put on hold.
    on_hold_candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    on_hold_app = _make_application(
        db_session, job, on_hold_candidate, status="on_hold", previous_status="received"
    )

    response = client.post("/screening/re-evaluate-all")
    assert response.status_code == 200
    body = response.json()
    # This runs against the shared dev DB (see conftest.py's db_session fixture), which
    # already has its own received/screened applications outside this test's control --
    # so counts are asserted as lower bounds including at least these two, rather than
    # exact totals. The per-application outcomes below are the real assertions.
    assert body["considered"] >= 2  # at least received_app + screened_app
    assert body["updated"] >= 2

    db_session.refresh(received_app)
    db_session.refresh(screened_app)
    db_session.refresh(decided_app)
    db_session.refresh(on_hold_app)

    assert received_app.status == "screened"
    assert received_app.composite_score == 95.0
    assert screened_app.status == "screened"
    assert screened_app.composite_score == 95.0  # refreshed even though status didn't change

    # Untouched -- never re-screened.
    assert decided_app.status == "hr_selected"
    assert decided_app.composite_score == 99.0
    assert on_hold_app.status == "on_hold"
    assert on_hold_app.composite_score is None


def test_re_evaluate_all_counts_not_ready_and_failed_separately(client, db_session, monkeypatch):
    from app.ai_services.resume_matcher import ResumeMatchError

    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session)

    # No parsed_fields yet -- not ready to be screened at all.
    not_ready_candidate = _make_candidate(db_session, parsed_fields=None)
    not_ready_app = _make_application(db_session, job, not_ready_candidate, status="received")

    # Ready, but the AI call fails.
    failing_candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})
    failing_app = _make_application(db_session, job, failing_candidate, status="received")

    response = client.post("/screening/re-evaluate-all")
    assert response.status_code == 200
    body = response.json()
    # Same shared-dev-DB caveat as the test above -- these are lower bounds, not exact
    # totals. The real assertions are the two applications' own final state below.
    assert body["not_ready"] >= 1
    assert body["failed"] >= 1

    db_session.refresh(not_ready_app)
    db_session.refresh(failing_app)
    assert not_ready_app.status == "received"
    assert failing_app.status == "received"
