import uuid

import pytest

from app.core.crypto import encrypt
from app.models.application import Application, TERMINAL_APPLICATION_STATUSES
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user_integration import UserIntegration


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, full_name="Jane Doe", **kwargs) -> Candidate:
    candidate = Candidate(full_name=full_name, **kwargs)
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


# --- GET /applications/{id}/candidate-detail -- next-actions lookup ---


def _make_application_with_status(db_session, job, candidate, status, **kwargs):
    from app.models.application import Application

    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def test_candidate_detail_received_status_offers_screen_one_click(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "received")

    response = client.get(f"/applications/{application.id}/candidate-detail")

    assert response.status_code == 200
    body = response.json()
    assert body["job_title"] == job.title
    assert body["candidate"]["id"] == str(candidate.id)
    action_keys = [a["key"] for a in body["next_actions"]]
    assert action_keys == ["screen"]
    action = body["next_actions"][0]
    assert action["kind"] == "one_click"
    assert action["method"] == "POST"
    assert action["endpoint"] == f"/applications/{application.id}/screen"


def test_candidate_detail_screened_status_offers_both_shortlist_decisions(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "screened")

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    actions = {a["key"]: a for a in body["next_actions"]}

    assert actions["shortlist_select"]["body"] == {"decision": "select"}
    assert actions["shortlist_reject"]["body"] == {"decision": "reject"}
    assert actions["shortlist_reject"]["confirm"] is True


def test_candidate_detail_hr_selected_offers_schedule_navigate_and_validate_salary_one_click(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "hr_selected")

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    actions = {a["key"]: a for a in body["next_actions"]}

    assert actions["schedule_interview"]["kind"] == "navigate"
    assert actions["schedule_interview"]["route"] == f"/interviews?jobId={job.id}"
    assert actions["validate_salary"]["kind"] == "one_click"
    assert actions["validate_salary"]["endpoint"] == f"/applications/{application.id}/validate-salary"


def test_candidate_detail_interview_selected_offers_only_validate_salary(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "interview_selected")

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    action_keys = [a["key"] for a in body["next_actions"]]

    assert action_keys == ["validate_salary"]


def test_candidate_detail_interview_scheduled_offers_feedback_actions_for_latest_interview(client, db_session):
    from app.models.interview import Interview

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "interview_scheduled")
    interview = Interview(application_id=application.id)
    db_session.add(interview)
    db_session.commit()
    db_session.refresh(interview)

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    actions = {a["key"]: a for a in body["next_actions"]}

    assert actions["interview_selected"]["endpoint"] == f"/interviews/{interview.id}/feedback"
    assert actions["interview_selected"]["method"] == "PATCH"
    assert actions["interview_rejected"]["body"] == {"decision": "rejected"}


def test_candidate_detail_bgv_without_valid_documents_cannot_clear(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "bgv_requested")

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    action_keys = [a["key"] for a in body["next_actions"]]

    assert "bgv_clear" not in action_keys
    assert "bgv_reject" in action_keys
    assert "manage_bgv_documents" in action_keys


def test_candidate_detail_bgv_with_all_valid_documents_can_clear(client, db_session):
    from app.models.bgv_document import BgvDocument

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "bgv_pending")
    doc = BgvDocument(application_id=application.id, doc_type="pan", validation_status="valid")
    db_session.add(doc)
    db_session.commit()

    body = client.get(f"/applications/{application.id}/candidate-detail").json()
    actions = {a["key"]: a for a in body["next_actions"]}

    assert actions["bgv_clear"]["body"] == {"decision": "clear"}


def test_candidate_detail_terminal_status_has_no_next_actions(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "onboarding_completed")

    body = client.get(f"/applications/{application.id}/candidate-detail").json()

    assert body["next_actions"] == []


def test_candidate_detail_includes_other_applications_for_same_candidate(client, db_session):
    job_a = _make_job(db_session)
    job_b = JobRole(title="Job B")
    db_session.add(job_b)
    db_session.commit()
    db_session.refresh(job_b)
    candidate = _make_candidate(db_session)
    app_a = _make_application_with_status(db_session, job_a, candidate, "received")
    app_b = _make_application_with_status(db_session, job_b, candidate, "screened")

    body = client.get(f"/applications/{app_a.id}/candidate-detail").json()

    other_ids = [o["application_id"] for o in body["other_applications"]]
    assert other_ids == [str(app_b.id)]
    assert body["other_applications"][0]["job_title"] == "Job B"


def test_candidate_detail_not_found(client):
    response = client.get(f"/applications/{uuid.uuid4()}/candidate-detail")
    assert response.status_code == 404


# --- POST /applications/{id}/message ---


def test_message_candidate_without_google_connection_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="candidate@example.com")
    application = _make_application_with_status(db_session, job, candidate, "received")

    response = client.post(
        f"/applications/{application.id}/message", json={"subject": "Hi", "body": "Hello there"}
    )

    assert response.status_code == 400
    assert "Connect Google" in response.json()["detail"]


def test_message_candidate_without_email_on_file_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=None)
    application = _make_application_with_status(db_session, job, candidate, "received")

    response = client.post(
        f"/applications/{application.id}/message", json={"subject": "Hi", "body": "Hello"}
    )

    assert response.status_code == 400


def test_message_candidate_sends_real_email_via_connected_gmail(client, db_session, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="candidate@example.com")
    application = _make_application_with_status(db_session, job, candidate, "received")

    from app.core.security import decode_access_token

    token = client.headers["Authorization"].split(" ")[1]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    db_session.add(UserIntegration(user_id=user_id, provider="google", refresh_token=encrypt("refresh-token")))
    db_session.commit()

    captured = {}
    monkeypatch.setattr(
        "app.candidates.applications_router.send_email",
        lambda refresh_token, **kwargs: captured.update(kwargs) or "msg_1",
    )

    response = client.post(
        f"/applications/{application.id}/message",
        json={"subject": "Interview update", "body": "Great news!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"sent": True, "to": "candidate@example.com"}
    assert captured["to"] == "candidate@example.com"
    assert captured["subject"] == "Interview update"

    from app.models.audit_log import AuditLog

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "candidate_email_sent")
        .one_or_none()
    )
    assert entry is not None
    assert entry.details["to"] == "candidate@example.com"


def test_message_candidate_gmail_failure_returns_502(client, db_session, monkeypatch):
    from app.integrations.gmail import GmailError

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="candidate@example.com")
    application = _make_application_with_status(db_session, job, candidate, "received")

    from app.core.security import decode_access_token

    token = client.headers["Authorization"].split(" ")[1]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    db_session.add(UserIntegration(user_id=user_id, provider="google", refresh_token=encrypt("refresh-token")))
    db_session.commit()

    def fake_send_email(refresh_token, **kwargs):
        raise GmailError("Gmail is down")

    monkeypatch.setattr("app.candidates.applications_router.send_email", fake_send_email)

    response = client.post(
        f"/applications/{application.id}/message", json={"subject": "Hi", "body": "Hello"}
    )

    assert response.status_code == 502


def test_message_candidate_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/message", json={"subject": "Hi", "body": "Hello"}
    )
    assert response.status_code == 404


# --- POST /applications/{id}/hold, /resume -- on_hold status transitions ---


@pytest.mark.parametrize(
    "status", ["received", "screened", "hr_selected", "interview_scheduled", "salary_ok", "bgv_pending", "offer_sent", "onboarding_started"]
)
def test_hold_application_from_non_terminal_status_succeeds(client, db_session, status):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, status)

    response = client.post(f"/applications/{application.id}/hold")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "on_hold"
    assert body["previous_status"] == status
    db_session.refresh(application)
    assert application.status == "on_hold"
    assert application.previous_status == status


def test_hold_application_logs_audit_entry(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "screened")

    client.post(f"/applications/{application.id}/hold")

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "application_put_on_hold")
        .one()
    )
    assert entry.details["previous_status"] == "screened"


@pytest.mark.parametrize("status", list(TERMINAL_APPLICATION_STATUSES))
def test_hold_application_from_terminal_status_blocked(client, db_session, status):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, status)

    response = client.post(f"/applications/{application.id}/hold")

    assert response.status_code == 400
    db_session.refresh(application)
    assert application.status == status
    assert application.previous_status is None


def test_hold_application_already_on_hold_blocked(client, db_session):
    # Re-holding an already on-hold application must be rejected, not a silent no-op --
    # doing so would overwrite previous_status with 'on_hold' itself, permanently losing
    # the real status resume should restore.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="screened")

    response = client.post(f"/applications/{application.id}/hold")

    assert response.status_code == 400
    db_session.refresh(application)
    assert application.status == "on_hold"
    assert application.previous_status == "screened"


def test_hold_application_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/hold")
    assert response.status_code == 404


def test_resume_application_from_hold_succeeds(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="hr_selected")

    response = client.post(f"/applications/{application.id}/resume")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "hr_selected"
    assert body["previous_status"] is None
    db_session.refresh(application)
    assert application.status == "hr_selected"
    assert application.previous_status is None


def test_resume_application_logs_audit_entry(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="bgv_pending")

    client.post(f"/applications/{application.id}/resume")

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "application_resumed_from_hold")
        .one()
    )
    assert entry.details["restored_status"] == "bgv_pending"


def test_resume_application_from_non_on_hold_status_rejected(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "screened")

    response = client.post(f"/applications/{application.id}/resume")

    assert response.status_code == 400
    db_session.refresh(application)
    assert application.status == "screened"


def test_resume_application_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/resume")
    assert response.status_code == 404


# --- on_hold blocks other pipeline actions ---


def test_on_hold_blocks_screen(client, db_session):
    job = _make_job(db_session, jd_text="A real JD")
    candidate = _make_candidate(db_session, parsed_fields={"skills": []})
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="received")

    response = client.post(f"/applications/{application.id}/screen")

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


def test_on_hold_blocks_shortlist_decision(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="screened")

    response = client.post(
        f"/applications/{application.id}/shortlist-decision", json={"decision": "select"}
    )

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


def test_on_hold_blocks_schedule_interview(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="hr_selected")

    response = client.post(
        f"/applications/{application.id}/interviews", json={"scheduled_at": "2026-09-01T10:00:00Z"}
    )

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


def test_on_hold_blocks_validate_salary(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(
        db_session, job, candidate, "on_hold", previous_status="hr_selected", expected_salary=100000
    )

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


def test_on_hold_blocks_bgv_request(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="salary_approved")

    response = client.post(f"/applications/{application.id}/bgv/request")

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


def test_on_hold_blocks_offer_generate(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, full_name="Jane Doe")
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="bgv_cleared")

    response = client.post(
        f"/applications/{application.id}/offer/generate", json={"start_date": "2026-09-01"}
    )

    assert response.status_code == 400
    assert "on hold" in response.json()["detail"].lower()


# --- DELETE /applications/{id} ---


def test_delete_received_application_succeeds(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "received")
    application_id = application.id

    response = client.delete(f"/applications/{application_id}")

    assert response.status_code == 204
    assert db_session.get(Application, application_id) is None


def test_delete_screened_application_blocked(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "screened")

    response = client.delete(f"/applications/{application.id}")

    assert response.status_code == 400
    assert db_session.get(Application, application.id) is not None


def test_delete_on_hold_application_blocked(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application_with_status(db_session, job, candidate, "on_hold", previous_status="received")

    response = client.delete(f"/applications/{application.id}")

    assert response.status_code == 400
    assert db_session.get(Application, application.id) is not None


def test_delete_application_not_found(client):
    response = client.delete(f"/applications/{uuid.uuid4()}")
    assert response.status_code == 404
