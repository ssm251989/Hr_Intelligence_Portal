import uuid
from datetime import datetime, timedelta, timezone

from app.core.crypto import encrypt
from app.integrations.google_calendar import GoogleCalendarError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration

FAKE_QUESTIONS_RESULT = {
    "technical_questions": ["Explain how you'd design a REST API for X."],
    "behavioral_questions": ["Tell me about a time you disagreed with a teammate."],
    "questions_to_probe_gaps": ["Have you worked with Kubernetes before?"],
}


def _make_job(db_session, jd_text=None) -> JobRole:
    job = JobRole(title="Backend Engineer", jd_text=jd_text)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, name="Jane Doe") -> Candidate:
    candidate = Candidate(full_name=name)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="hr_selected", missing_skills=None) -> Application:
    application = Application(
        job_role_id=job.id, candidate_id=candidate.id, status=status, missing_skills=missing_skills
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_interviewer(db_session) -> User:
    user = User(email="interviewer@example.com", hashed_password="x", role="interviewer")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _connect_google(db_session, user) -> UserIntegration:
    integration = UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt("refresh-token"))
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def _make_interview(db_session, application, scheduled_at=None) -> Interview:
    interview = Interview(
        application_id=application.id,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
    )
    db_session.add(interview)
    db_session.commit()
    db_session.refresh(interview)
    return interview


def test_schedule_interview_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")
    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={"scheduled_at": scheduled_at, "meeting_link": "https://meet.example.com/abc"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["application_id"] == str(application.id)
    assert body["meeting_link"] == "https://meet.example.com/abc"

    db_session.refresh(application)
    assert application.status == "interview_scheduled"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(body["id"]), AuditLog.action == "interview_scheduled")
        .one_or_none()
    )
    assert audit_entry is not None


def test_schedule_interview_requires_hr_selected_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={"scheduled_at": datetime.now(timezone.utc).isoformat()},
    )

    assert response.status_code == 400


def test_schedule_interview_application_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/interviews",
        json={"scheduled_at": datetime.now(timezone.utc).isoformat()},
    )
    assert response.status_code == 404


def test_schedule_interview_with_invalid_interviewer_returns_404(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={"scheduled_at": datetime.now(timezone.utc).isoformat(), "interviewer_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


def test_schedule_second_interview_round_allowed(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={"scheduled_at": datetime.now(timezone.utc).isoformat()},
    )

    assert response.status_code == 201


def test_list_interviews_for_application(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    earlier = _make_interview(db_session, application, scheduled_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    later = _make_interview(db_session, application, scheduled_at=datetime(2026, 2, 1, tzinfo=timezone.utc))

    response = client.get(f"/applications/{application.id}/interviews")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(earlier.id), str(later.id)]


def test_get_interview_not_found(client):
    response = client.get(f"/interviews/{uuid.uuid4()}")
    assert response.status_code == 404


def test_submit_interview_feedback_ratings_only(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    interview = _make_interview(db_session, application)

    response = client.patch(
        f"/interviews/{interview.id}/feedback",
        json={"technical_rating": 4, "communication_rating": 5, "comments": "Solid candidate"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["technical_rating"] == 4
    assert body["decision"] is None

    db_session.refresh(application)
    assert application.status == "interview_scheduled"


def test_submit_interview_feedback_with_decision_selected(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    interview = _make_interview(db_session, application)

    response = client.patch(
        f"/interviews/{interview.id}/feedback",
        json={"overall_rating": 5, "decision": "selected"},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "selected"

    db_session.refresh(application)
    assert application.status == "interview_selected"


def test_submit_interview_feedback_with_decision_rejected(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    interview = _make_interview(db_session, application)

    response = client.patch(f"/interviews/{interview.id}/feedback", json={"decision": "rejected"})

    assert response.status_code == 200

    db_session.refresh(application)
    assert application.status == "interview_rejected"


def test_submit_interview_feedback_decision_requires_interview_scheduled_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_selected")
    interview = _make_interview(db_session, application)

    response = client.patch(f"/interviews/{interview.id}/feedback", json={"decision": "rejected"})

    assert response.status_code == 400


def test_submit_interview_feedback_not_found(client):
    response = client.patch(f"/interviews/{uuid.uuid4()}/feedback", json={"decision": "selected"})
    assert response.status_code == 404


def test_generate_interview_questions_success(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.scheduling.router.generate_interview_questions",
        lambda jd_text, missing_skills: FAKE_QUESTIONS_RESULT,
    )

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and Kubernetes.")
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, missing_skills=["Kubernetes"])

    response = client.post(f"/applications/{application.id}/interview-questions")

    assert response.status_code == 200
    assert response.json() == FAKE_QUESTIONS_RESULT

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_interview_questions_generated")
        .one_or_none()
    )
    assert audit_entry is not None


def test_generate_interview_questions_without_jd_returns_400(client, db_session):
    job = _make_job(db_session, jd_text=None)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/applications/{application.id}/interview-questions")

    assert response.status_code == 400


def test_generate_interview_questions_application_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/interview-questions")
    assert response.status_code == 404


def test_schedule_interview_without_connected_calendar_uses_manual_link(client, db_session):
    # No Google integration for the interviewer -- existing manual-link behavior must be untouched.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")
    interviewer = _make_interviewer(db_session)
    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={
            "interviewer_id": str(interviewer.id),
            "scheduled_at": scheduled_at,
            "meeting_link": "https://meet.example.com/manual",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_link"] == "https://meet.example.com/manual"
    assert body["calendar_event_id"] is None
    assert body["calendar_link"] is None


def test_schedule_interview_without_interviewer_uses_manual_link(client, db_session):
    # No interviewer assigned at all -- nothing to look up a calendar connection for.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")

    response = client.post(
        f"/applications/{application.id}/interviews",
        json={
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "meeting_link": "https://meet.example.com/manual",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_link"] == "https://meet.example.com/manual"
    assert body["calendar_event_id"] is None
    assert body["calendar_link"] is None


def test_schedule_interview_with_connected_calendar_creates_real_event(client, db_session, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")
    interviewer = _make_interviewer(db_session)
    _connect_google(db_session, interviewer)

    captured = {}

    def fake_create_calendar_event(refresh_token, **kwargs):
        captured["refresh_token"] = refresh_token
        captured["kwargs"] = kwargs
        return {"event_id": "evt_123", "html_link": "https://calendar.google.com/event?eid=evt_123"}

    monkeypatch.setattr("app.scheduling.router.create_calendar_event", fake_create_calendar_event)

    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    response = client.post(
        f"/applications/{application.id}/interviews",
        json={"interviewer_id": str(interviewer.id), "scheduled_at": scheduled_at},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["calendar_event_id"] == "evt_123"
    assert body["calendar_link"] == "https://calendar.google.com/event?eid=evt_123"

    # The stored refresh token was decrypted before being handed to the calendar client.
    assert captured["refresh_token"] == "refresh-token"
    assert captured["kwargs"]["attendee_emails"] == [interviewer.email]


def test_schedule_interview_calendar_failure_falls_back_to_manual_link(client, db_session, monkeypatch):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")
    interviewer = _make_interviewer(db_session)
    _connect_google(db_session, interviewer)

    def fake_create_calendar_event(refresh_token, **kwargs):
        raise GoogleCalendarError("Google API is down")

    monkeypatch.setattr("app.scheduling.router.create_calendar_event", fake_create_calendar_event)

    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    response = client.post(
        f"/applications/{application.id}/interviews",
        json={
            "interviewer_id": str(interviewer.id),
            "scheduled_at": scheduled_at,
            "meeting_link": "https://meet.example.com/manual",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_link"] == "https://meet.example.com/manual"
    assert body["calendar_event_id"] is None
    assert body["calendar_link"] is None

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "calendar_event_creation_failed", AuditLog.entity_id == application.id)
        .one_or_none()
    )
    assert audit_entry is not None
