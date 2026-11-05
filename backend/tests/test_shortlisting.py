import uuid

import pytest
from fastapi import HTTPException

from app.ai_services.shortlist_feedback_generator import ShortlistFeedbackGenerationError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.shortlisting import service as shortlisting_service


def _make_job(db_session) -> JobRole:
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, name="Jane Doe", **kwargs) -> Candidate:
    candidate = Candidate(full_name=name, **kwargs)
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


def test_shortlist_queue_sorted_by_match_score(client, db_session):
    job = _make_job(db_session)
    other_job = _make_job(db_session)

    low_scorer = _make_application(db_session, job, _make_candidate(db_session, "Low"), status="screened", match_score=60)
    high_scorer = _make_application(db_session, job, _make_candidate(db_session, "High"), status="screened", match_score=90)
    _make_application(db_session, job, _make_candidate(db_session, "Unscreened"), status="received")
    _make_application(db_session, other_job, _make_candidate(db_session, "OtherJob"), status="screened", match_score=99)

    response = client.get(f"/jobs/{job.id}/shortlist")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(high_scorer.id), str(low_scorer.id)]


def test_shortlist_decision_select(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=75)

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "select", "notes": "Strong fit", "decided_by": "hr_jane"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "hr_shortlisting_decision")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.actor == "hr_jane"
    assert audit_entry.details["decision"] == "select"
    assert audit_entry.details["notes"] == "Strong fit"


def test_shortlist_decision_reject(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=40)

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "hr_rejected"


def test_shortlist_decision_defaults_actor_to_current_user_email(client, db_session, make_auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=75)

    headers = make_auth_headers(role="recruiter", email="recruiter@example.com")
    client.post(f"/applications/{application.id}/shortlist-decision", json={"decision": "select"}, headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "hr_shortlisting_decision")
        .one_or_none()
    )
    assert audit_entry.actor == "recruiter@example.com"


def test_shortlist_decision_requires_screened_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="received")

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "select"},
    )

    assert response.status_code == 400


def test_shortlist_decision_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/shortlist-decision",
        json={"decision": "select"},
    )
    assert response.status_code == 404


# --- Redesign: GET /shortlisting/list (scoped to the shortlisting stage only) ---


def test_list_shortlisting_scopes_to_the_four_shortlist_states(client, db_session):
    job = _make_job(db_session)
    under_review = _make_application(db_session, job, _make_candidate(db_session, "Under Review"), status="screened")
    _make_application(db_session, job, _make_candidate(db_session, "Not Yet Screened"), status="received")
    on_hold_here = _make_application(db_session, job, _make_candidate(db_session, "On Hold Here"), status="on_hold")
    on_hold_here.previous_status = "screened"
    db_session.commit()
    unrelated_hold = _make_application(db_session, job, _make_candidate(db_session, "On Hold Elsewhere"), status="on_hold")
    unrelated_hold.previous_status = "interview_scheduled"
    db_session.commit()

    response = client.get("/shortlisting/list", params={"job_role_id": str(job.id), "page_size": 200})
    assert response.status_code == 200
    ids = {item["application_id"] for item in response.json()["items"]}
    assert str(under_review.id) in ids
    assert str(on_hold_here.id) in ids
    assert not any(a["candidate_name"] == "Not Yet Screened" for a in response.json()["items"])
    assert str(unrelated_hold.id) not in ids


def test_list_shortlisting_filters_by_shortlist_status(client, db_session):
    job = _make_job(db_session)
    shortlisted = _make_application(db_session, job, _make_candidate(db_session, "Shortlisted"), status="hr_selected")
    _make_application(db_session, job, _make_candidate(db_session, "Under Review Two"), status="screened")

    response = client.get(
        "/shortlisting/list", params={"job_role_id": str(job.id), "shortlist_status": "shortlisted", "page_size": 200}
    )
    ids = {item["application_id"] for item in response.json()["items"]}
    assert ids == {str(shortlisted.id)}


def test_list_shortlisting_requires_auth(anonymous_client):
    response = anonymous_client.get("/shortlisting/list")
    assert response.status_code == 401


def test_export_shortlisting_matches_list_scope(client, db_session):
    job = _make_job(db_session)
    on_hold_here = _make_application(db_session, job, _make_candidate(db_session, "Export On Hold"), status="on_hold")
    on_hold_here.previous_status = "screened"
    db_session.commit()

    response = client.get("/shortlisting/export", params={"job_role_id": str(job.id)})
    assert response.status_code == 200
    ids = {item["application_id"] for item in response.json()}
    assert str(on_hold_here.id) in ids


# --- Redesign: shortlist_status_of / update_shortlist_status (4-state transition rules) ---


def test_shortlist_status_of_maps_real_application_statuses(db_session):
    job = _make_job(db_session)
    under_review = _make_application(db_session, job, _make_candidate(db_session), status="screened")
    shortlisted = _make_application(db_session, job, _make_candidate(db_session), status="hr_selected")
    not_shortlisted = _make_application(db_session, job, _make_candidate(db_session), status="hr_rejected")
    on_hold = _make_application(db_session, job, _make_candidate(db_session), status="on_hold")
    on_hold.previous_status = "screened"
    db_session.commit()
    unrelated_hold = _make_application(db_session, job, _make_candidate(db_session), status="on_hold")
    unrelated_hold.previous_status = "interview_scheduled"
    db_session.commit()
    out_of_scope = _make_application(db_session, job, _make_candidate(db_session), status="received")

    assert shortlisting_service.shortlist_status_of(under_review) == "under_review"
    assert shortlisting_service.shortlist_status_of(shortlisted) == "shortlisted"
    assert shortlisting_service.shortlist_status_of(not_shortlisted) == "not_shortlisted"
    assert shortlisting_service.shortlist_status_of(on_hold) == "on_hold"
    assert shortlisting_service.shortlist_status_of(unrelated_hold) is None
    assert shortlisting_service.shortlist_status_of(out_of_scope) is None


@pytest.mark.parametrize(
    "target,expected_application_status",
    [("shortlisted", "hr_selected"), ("not_shortlisted", "hr_rejected"), ("on_hold", "on_hold")],
)
def test_update_shortlist_status_under_review_to_each_valid_target(db_session, target, expected_application_status):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened")

    updated = shortlisting_service.update_shortlist_status(db_session, application, target, "hr@example.com")

    assert updated.status == expected_application_status
    if target == "on_hold":
        assert updated.previous_status == "screened"
    else:
        assert updated.previous_status is None

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "shortlist_status_updated")
        .one()
    )
    assert audit_entry.details["previous_shortlist_status"] == "under_review"
    assert audit_entry.details["new_shortlist_status"] == target


def test_update_shortlist_status_on_hold_back_to_under_review_restores_previous_status(db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="on_hold")
    application.previous_status = "screened"
    db_session.commit()

    updated = shortlisting_service.update_shortlist_status(db_session, application, "under_review", "hr@example.com")

    assert updated.status == "screened"
    assert updated.previous_status is None


@pytest.mark.parametrize("target,expected_application_status", [("shortlisted", "hr_selected"), ("not_shortlisted", "hr_rejected")])
def test_update_shortlist_status_on_hold_directly_to_a_decision(db_session, target, expected_application_status):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="on_hold")
    application.previous_status = "screened"
    db_session.commit()

    updated = shortlisting_service.update_shortlist_status(db_session, application, target, "hr@example.com")

    assert updated.status == expected_application_status
    assert updated.previous_status is None


@pytest.mark.parametrize("terminal_status", ["hr_selected", "hr_rejected"])
@pytest.mark.parametrize("target", ["under_review", "shortlisted", "on_hold", "not_shortlisted"])
def test_update_shortlist_status_terminal_states_reject_every_transition(db_session, terminal_status, target):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status=terminal_status)

    with pytest.raises(HTTPException) as exc_info:
        shortlisting_service.update_shortlist_status(db_session, application, target, "hr@example.com")
    assert exc_info.value.status_code == 400


def test_update_shortlist_status_rejects_same_status_no_op(db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened")

    with pytest.raises(HTTPException) as exc_info:
        shortlisting_service.update_shortlist_status(db_session, application, "under_review", "hr@example.com")
    assert exc_info.value.status_code == 400


def test_update_shortlist_status_out_of_scope_application_rejected(db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="received")

    with pytest.raises(HTTPException) as exc_info:
        shortlisting_service.update_shortlist_status(db_session, application, "shortlisted", "hr@example.com")
    assert exc_info.value.status_code == 400


def test_update_shortlist_status_records_reason_and_feedback(db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened")

    shortlisting_service.update_shortlist_status(
        db_session, application, "not_shortlisted", "hr@example.com",
        reason="Needs more experience", feedback="Strong fundamentals but light on production experience.",
    )

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "shortlist_status_updated")
        .one()
    )
    assert audit_entry.details["reason"] == "Needs more experience"
    assert audit_entry.details["feedback"] == "Strong fundamentals but light on production experience."


# --- Redesign: POST /applications/{id}/shortlist-status (the HTTP endpoint) ---


def test_shortlist_status_endpoint_updates_and_returns_the_application(client, db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened")

    response = client.post(
        f"/applications/{application.id}/shortlist-status",
        json={"target_status": "shortlisted", "reason": "Move to Interview"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"


def test_shortlist_status_endpoint_rejects_invalid_transition(client, db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="hr_selected")

    response = client.post(
        f"/applications/{application.id}/shortlist-status", json={"target_status": "on_hold"}
    )
    assert response.status_code == 400


def test_shortlist_status_endpoint_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/shortlist-status", json={"target_status": "shortlisted"}
    )
    assert response.status_code == 404


def test_shortlist_status_endpoint_requires_auth(anonymous_client):
    response = anonymous_client.post(
        f"/applications/{uuid.uuid4()}/shortlist-status", json={"target_status": "shortlisted"}
    )
    assert response.status_code == 401


# --- Redesign: POST /applications/{id}/shortlist-feedback-suggestion (AI Suggestion) ---


def test_shortlist_feedback_suggestion_uses_real_screening_data(client, db_session, monkeypatch):
    captured = {}

    def fake_generate(candidate_name, job_title, composite_score, matched_skills, missing_skills):
        captured.update(
            candidate_name=candidate_name, job_title=job_title, composite_score=composite_score,
            matched_skills=matched_skills, missing_skills=missing_skills,
        )
        return "Drafted feedback referencing the real inputs."

    monkeypatch.setattr("app.shortlisting.router.generate_shortlist_feedback", fake_generate)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, "Feedback Candidate", parsed_fields={"skills": ["Python", "SQL", "Docker"]})
    application = _make_application(
        db_session, job, candidate, status="screened", composite_score=82.0, missing_skills=["Docker"]
    )

    response = client.post(f"/applications/{application.id}/shortlist-feedback-suggestion")

    assert response.status_code == 200
    assert response.json()["suggested_feedback"] == "Drafted feedback referencing the real inputs."
    assert captured["candidate_name"] == "Feedback Candidate"
    assert captured["job_title"] == job.title
    assert captured["composite_score"] == 82.0
    assert set(captured["matched_skills"]) == {"Python", "SQL"}
    assert captured["missing_skills"] == ["Docker"]

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_shortlist_feedback_suggested")
        .one()
    )
    assert audit_entry.details["suggested_feedback"] == "Drafted feedback referencing the real inputs."


def test_shortlist_feedback_suggestion_never_mutates_the_application(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.shortlisting.router.generate_shortlist_feedback",
        lambda **kwargs: "Draft only.",
    )
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened", composite_score=70.0)

    client.post(f"/applications/{application.id}/shortlist-feedback-suggestion")

    db_session.refresh(application)
    assert application.status == "screened"  # advisory only -- never auto-saved


def test_shortlist_feedback_suggestion_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_generate(**kwargs):
        raise ShortlistFeedbackGenerationError("Failed to generate shortlist feedback suggestion: boom")

    monkeypatch.setattr("app.shortlisting.router.generate_shortlist_feedback", fake_generate)

    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened", composite_score=70.0)

    response = client.post(f"/applications/{application.id}/shortlist-feedback-suggestion")
    assert response.status_code == 502


def test_shortlist_feedback_suggestion_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/shortlist-feedback-suggestion")
    assert response.status_code == 404


def test_shortlist_feedback_suggestion_requires_auth(anonymous_client):
    response = anonymous_client.post(f"/applications/{uuid.uuid4()}/shortlist-feedback-suggestion")
    assert response.status_code == 401


# --- Redesign: POST /shortlisting/bulk-decision (bulk select-and-decide) ---


def test_bulk_decision_shortlists_every_eligible_application(client, db_session):
    job = _make_job(db_session)
    app_a = _make_application(db_session, job, _make_candidate(db_session, "Bulk A"), status="screened")
    app_b = _make_application(db_session, job, _make_candidate(db_session, "Bulk B"), status="screened")
    app_c = _make_application(db_session, job, _make_candidate(db_session, "Bulk C"), status="screened")

    response = client.post(
        "/shortlisting/bulk-decision",
        json={
            "application_ids": [str(app_a.id), str(app_b.id), str(app_c.id)],
            "target_status": "shortlisted",
            "reason": "Move to Interview",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["succeeded"]) == {str(app_a.id), str(app_b.id), str(app_c.id)}
    assert body["skipped"] == []

    for app in (app_a, app_b, app_c):
        db_session.refresh(app)
        assert app.status == "hr_selected"

    for app in (app_a, app_b, app_c):
        audit_entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_id == app.id, AuditLog.action == "shortlist_status_updated")
            .one()
        )
        assert audit_entry.details["reason"] == "Move to Interview"


def test_bulk_decision_rejects_every_eligible_application(client, db_session):
    job = _make_job(db_session)
    app_a = _make_application(db_session, job, _make_candidate(db_session, "Reject A"), status="screened")
    app_b = _make_application(db_session, job, _make_candidate(db_session, "Reject B"), status="screened")

    response = client.post(
        "/shortlisting/bulk-decision",
        json={"application_ids": [str(app_a.id), str(app_b.id)], "target_status": "not_shortlisted"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["succeeded"]) == {str(app_a.id), str(app_b.id)}
    assert body["skipped"] == []

    db_session.refresh(app_a)
    db_session.refresh(app_b)
    assert app_a.status == "hr_rejected"
    assert app_b.status == "hr_rejected"


def test_bulk_decision_partial_failure_one_already_decided(client, db_session):
    job = _make_job(db_session)
    already_decided = _make_application(
        db_session, job, _make_candidate(db_session, "Already Decided"), status="hr_selected"
    )
    eligible_one = _make_application(db_session, job, _make_candidate(db_session, "Eligible One"), status="screened")
    eligible_two = _make_application(db_session, job, _make_candidate(db_session, "Eligible Two"), status="screened")

    response = client.post(
        "/shortlisting/bulk-decision",
        json={
            "application_ids": [str(already_decided.id), str(eligible_one.id), str(eligible_two.id)],
            "target_status": "not_shortlisted",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["succeeded"]) == {str(eligible_one.id), str(eligible_two.id)}
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["application_id"] == str(already_decided.id)
    assert "terminal" in body["skipped"][0]["reason"].lower()

    db_session.refresh(already_decided)
    db_session.refresh(eligible_one)
    db_session.refresh(eligible_two)
    assert already_decided.status == "hr_selected"  # untouched -- the invalid one, not silently overwritten
    assert eligible_one.status == "hr_rejected"
    assert eligible_two.status == "hr_rejected"


def test_bulk_decision_skips_out_of_scope_and_nonexistent_applications(client, db_session):
    job = _make_job(db_session)
    out_of_scope = _make_application(db_session, job, _make_candidate(db_session, "Not Yet Screened"), status="received")
    missing_id = uuid.uuid4()

    response = client.post(
        "/shortlisting/bulk-decision",
        json={"application_ids": [str(out_of_scope.id), str(missing_id)], "target_status": "shortlisted"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == []
    skipped_by_id = {row["application_id"]: row["reason"] for row in body["skipped"]}
    assert "shortlisting stage" in skipped_by_id[str(out_of_scope.id)].lower()
    assert skipped_by_id[str(missing_id)] == "Application not found"


def test_bulk_decision_applies_the_same_transition_validation_per_id_as_the_single_endpoint(client, db_session):
    # Same rule as the single-candidate endpoint (Shortlisted/Not Shortlisted are terminal)
    # -- proves the bulk endpoint doesn't loosen validation just because it's a batch call.
    job = _make_job(db_session)
    terminal_app = _make_application(db_session, job, _make_candidate(db_session), status="hr_rejected")

    single_response = client.post(
        f"/applications/{terminal_app.id}/shortlist-status", json={"target_status": "shortlisted"}
    )
    bulk_response = client.post(
        "/shortlisting/bulk-decision",
        json={"application_ids": [str(terminal_app.id)], "target_status": "shortlisted"},
    )

    assert single_response.status_code == 400
    assert bulk_response.status_code == 200
    bulk_body = bulk_response.json()
    assert bulk_body["succeeded"] == []
    assert single_response.json()["detail"] in bulk_body["skipped"][0]["reason"]


def test_bulk_decision_requires_auth(anonymous_client):
    response = anonymous_client.post(
        "/shortlisting/bulk-decision", json={"application_ids": [], "target_status": "shortlisted"}
    )
    assert response.status_code == 401


def test_bulk_decision_rejects_invalid_target_status(client, db_session):
    job = _make_job(db_session)
    application = _make_application(db_session, job, _make_candidate(db_session), status="screened")

    response = client.post(
        "/shortlisting/bulk-decision",
        json={"application_ids": [str(application.id)], "target_status": "on_hold"},
    )
    assert response.status_code == 422  # bulk-decision only accepts shortlisted/not_shortlisted
