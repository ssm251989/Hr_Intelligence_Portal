import uuid
from datetime import datetime, timedelta, timezone

from app.ai_services.interview_question_generator import InterviewQuestionGenerationError
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
    assert body["scheduling_method"] == "manual"

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


def test_generate_interview_questions_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_generate_interview_questions(jd_text, missing_skills):
        raise InterviewQuestionGenerationError("Failed to generate interview questions: AI service timed out")

    monkeypatch.setattr(
        "app.scheduling.router.generate_interview_questions", fake_generate_interview_questions
    )

    job = _make_job(db_session, jd_text="We need a backend engineer skilled in Python and Kubernetes.")
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, missing_skills=["Kubernetes"])

    response = client.post(f"/applications/{application.id}/interview-questions")

    assert response.status_code == 502


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


def test_schedule_interview_with_corrupted_google_token_falls_back_to_manual_link(client, db_session):
    # A corrupted/invalid stored refresh token must not surface as a raw 500 -- it should
    # hit the same "never blocks scheduling" fallback as any other calendar failure.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")
    interviewer = _make_interviewer(db_session)
    integration = UserIntegration(
        user_id=interviewer.id, provider="google", refresh_token="not-a-valid-fernet-token"
    )
    db_session.add(integration)
    db_session.commit()

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


# --- GET /interviews (Interview List page) ---


def _unique_job_title(prefix: str) -> str:
    return f"{prefix} zzInterviewsList{uuid.uuid4().hex[:10]}"


def test_list_all_interviews_filters_by_job(client, db_session):
    job_a = JobRole(title=_unique_job_title("JobA"))
    job_b = JobRole(title=_unique_job_title("JobB"))
    db_session.add_all([job_a, job_b])
    db_session.commit()
    db_session.refresh(job_a)
    db_session.refresh(job_b)

    candidate = _make_candidate(db_session)
    app_a = _make_application(db_session, job_a, candidate, status="interview_scheduled")
    app_b = _make_application(db_session, job_b, candidate, status="interview_scheduled")
    interview_a = _make_interview(db_session, app_a)
    _make_interview(db_session, app_b)

    response = client.get("/interviews", params={"job_role_id": str(job_a.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["interview_id"] == str(interview_a.id)
    assert body["items"][0]["job_role_id"] == str(job_a.id)


def test_list_all_interviews_filters_by_interviewer(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    interviewer_a = _make_interviewer(db_session)
    interviewer_b = User(email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", role="interviewer")
    db_session.add(interviewer_b)
    db_session.commit()
    db_session.refresh(interviewer_b)

    app1 = _make_application(db_session, job, candidate, status="interview_scheduled")
    app2 = _make_application(db_session, job, candidate, status="interview_scheduled")
    interview_a = Interview(application_id=app1.id, interviewer_id=interviewer_a.id, scheduled_at=datetime.now(timezone.utc))
    interview_b = Interview(application_id=app2.id, interviewer_id=interviewer_b.id, scheduled_at=datetime.now(timezone.utc))
    db_session.add_all([interview_a, interview_b])
    db_session.commit()

    response = client.get("/interviews", params={"interviewer_id": str(interviewer_a.id)})

    assert response.status_code == 200
    body = response.json()
    ids = {item["interview_id"] for item in body["items"]}
    assert str(interview_a.id) in ids
    assert str(interview_b.id) not in ids


def test_list_all_interviews_shows_plaintext_interviewer_name_when_no_user_account(client, db_session):
    """An interview scheduled through the interviewer-first negotiation flow for a pool
    interviewer with no User account has interviewer_id NULL -- the List page must fall
    back to the plain-text interviewer_name captured at scheduling time (see Interview's
    own docstring) rather than showing a blank name."""
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    interview = Interview(
        application_id=application.id,
        interviewer_id=None,
        interviewer_name="Suresh A",
        interviewer_email="si@ctdtechs.com",
        scheduled_at=datetime.now(timezone.utc),
        scheduling_method="auto",
    )
    db_session.add(interview)
    db_session.commit()

    response = client.get("/interviews", params={"job_role_id": str(job.id)})

    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["interview_id"] == str(interview.id))
    assert row["interviewer_id"] is None
    assert row["interviewer_name"] == "Suresh A"


def test_list_all_interviews_filters_by_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    upcoming_app = _make_application(db_session, job, candidate, status="interview_scheduled")
    upcoming = _make_interview(
        db_session, upcoming_app, scheduled_at=datetime.now(timezone.utc) + timedelta(days=3)
    )

    awaiting_app = _make_application(db_session, job, candidate, status="interview_scheduled")
    awaiting = _make_interview(
        db_session, awaiting_app, scheduled_at=datetime.now(timezone.utc) - timedelta(days=1)
    )

    selected_app = _make_application(db_session, job, candidate, status="interview_selected")
    selected_interview = _make_interview(db_session, selected_app, scheduled_at=datetime.now(timezone.utc) - timedelta(days=2))
    selected_interview.decision = "selected"
    db_session.commit()

    rejected_app = _make_application(db_session, job, candidate, status="interview_rejected")
    rejected_interview = _make_interview(db_session, rejected_app, scheduled_at=datetime.now(timezone.utc) - timedelta(days=2))
    rejected_interview.decision = "rejected"
    db_session.commit()

    def ids_for(status):
        response = client.get("/interviews", params={"status": status, "page_size": 200})
        assert response.status_code == 200
        return {item["interview_id"] for item in response.json()["items"]}

    assert str(upcoming.id) in ids_for("upcoming")
    assert str(awaiting.id) not in ids_for("upcoming")

    assert str(awaiting.id) in ids_for("awaiting_feedback")
    assert str(upcoming.id) not in ids_for("awaiting_feedback")

    assert str(selected_interview.id) in ids_for("selected")
    assert str(rejected_interview.id) in ids_for("rejected")
    assert str(selected_interview.id) not in ids_for("rejected")


def test_list_all_interviews_filters_by_scheduling_method(client, db_session, tmp_path, monkeypatch):
    """The auto-vs-manual distinction: a manually-scheduled interview (POST
    /applications/{id}/interviews) must appear under scheduling_method=manual, and an
    auto-confirmed one (app/interview_scheduling/confirmation.py confirm_token) under
    scheduling_method=auto -- never mixed up or missing from either filter."""
    from openpyxl import load_workbook

    from app.interview_scheduling import confirmation as interview_confirmation
    from app.interview_scheduling import service as interview_scheduling_service
    from app.interview_scheduling.tracker import INTERVIEWER_POOL_SHEET, ensure_tracker_file

    # Manual interview.
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    manual_app = _make_application(db_session, job, candidate, status="hr_selected")
    manual_response = client.post(
        f"/applications/{manual_app.id}/interviews",
        json={"scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
    )
    assert manual_response.status_code == 201
    manual_interview_id = manual_response.json()["id"]

    # Auto-confirmed interview.
    auto_job_title = _unique_job_title("AutoConfirm")
    tracker_path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(tracker_path)
    workbook = load_workbook(tracker_path)
    workbook[INTERVIEWER_POOL_SHEET].append([auto_job_title, "Auto Interviewer"])
    workbook.save(tracker_path)

    auto_job = JobRole(title=auto_job_title, status="published")
    db_session.add(auto_job)
    db_session.commit()
    db_session.refresh(auto_job)
    auto_candidate = _make_candidate(db_session)
    auto_candidate.email = f"{uuid.uuid4().hex[:8]}@example.com"
    db_session.commit()
    auto_app = _make_application(db_session, auto_job, auto_candidate, status="hr_selected")
    auto_interviewer = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x",
        full_name="Auto Interviewer", role="interviewer",
    )
    db_session.add(auto_interviewer)
    db_session.commit()
    db_session.refresh(auto_interviewer)
    db_session.add(UserIntegration(user_id=auto_interviewer.id, provider="google", refresh_token=encrypt("tok")))
    db_session.commit()

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    monkeypatch.setattr(interview_confirmation, "send_hr_email", lambda *a, **k: None)
    monkeypatch.setattr(interview_confirmation, "create_calendar_event", lambda *a, **k: None)

    result = interview_confirmation.propose_interview_slots(
        db_session, auto_app, tracker_path=str(tracker_path), candidate=auto_candidate, job=auto_job,
        hr_integration=None, actor="recruiter@example.com",
    )
    assert result["slots_offered"] >= 1
    outcome = interview_confirmation.confirm_token(db_session, result["tokens"][0]["token"])
    assert outcome.status == "confirmed"
    auto_interview = db_session.query(Interview).filter(Interview.application_id == auto_app.id).one()

    manual_ids = {
        item["interview_id"]
        for item in client.get("/interviews", params={"scheduling_method": "manual", "page_size": 200}).json()["items"]
    }
    auto_ids = {
        item["interview_id"]
        for item in client.get("/interviews", params={"scheduling_method": "auto", "page_size": 200}).json()["items"]
    }

    assert manual_interview_id in manual_ids
    assert str(auto_interview.id) not in manual_ids
    assert str(auto_interview.id) in auto_ids
    assert manual_interview_id not in auto_ids


def test_list_all_interviews_pagination(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_scheduled")
    for _ in range(3):
        _make_interview(db_session, application)

    response = client.get("/interviews", params={"job_role_id": str(job.id), "page": 1, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_list_all_interviews_requires_auth(anonymous_client):
    response = anonymous_client.get("/interviews")
    assert response.status_code == 401


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
