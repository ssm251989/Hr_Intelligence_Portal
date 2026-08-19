import uuid
from datetime import datetime, timedelta, timezone

from openpyxl import load_workbook

from app.core.crypto import encrypt
from app.interview_scheduling import confirmation as interview_confirmation
from app.interview_scheduling import service as interview_scheduling_service
from app.interview_scheduling.tracker import INTERVIEW_LOG_SHEET, INTERVIEWER_POOL_SHEET, ensure_tracker_file
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview_confirmation_token import InterviewConfirmationToken
from app.models.interview_scheduling_settings import InterviewSchedulingSettings
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration


def _unique_job_title(prefix: str) -> str:
    return f"{prefix} zzInterviewConfirm{uuid.uuid4().hex[:10]}"


def _make_job(db_session, title) -> JobRole:
    job = JobRole(title=title, status="published")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, name="Jane Doe", email="jane@example.com") -> Candidate:
    candidate = Candidate(full_name=name, email=email)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="hr_selected") -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_interviewer(db_session, name) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name=name, role="interviewer"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _connect_google(db_session, user) -> UserIntegration:
    integration = UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt("fake-refresh-token"))
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def _setup_pool(tmp_path, job_title, interviewer_name):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, interviewer_name])
    workbook.save(path)
    return path


# --- propose_interview_slots ---


def test_propose_interview_slots_offers_three_and_sends_one_email(db_session, tmp_path, monkeypatch):
    job_title = _unique_job_title("Backend")
    tracker_path = _setup_pool(tmp_path, job_title, "Solo Interviewer")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    interviewer = _make_interviewer(db_session, "Solo Interviewer")
    _connect_google(db_session, interviewer)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    sent = {}
    monkeypatch.setattr(
        interview_confirmation,
        "send_email",
        lambda refresh_token, *, to, subject, body: sent.update(to=to, subject=subject, body=body) or "msg-id",
    )

    result = interview_confirmation.propose_interview_slots(
        db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
        sender_refresh_token="sender-token", actor="recruiter@example.com",
    )

    assert result["slots_offered"] == 3
    assert len(result["tokens"]) == 3
    assert sent["to"] == candidate.email
    assert all(t["url"] in sent["body"] for t in result["tokens"])

    tokens_in_db = (
        db_session.query(InterviewConfirmationToken)
        .filter(InterviewConfirmationToken.application_id == application.id)
        .all()
    )
    assert len(tokens_in_db) == 3
    for token_row in tokens_in_db:
        assert token_row.used_at is None
        assert token_row.invalidated_at is None
        assert token_row.interviewer_name == "Solo Interviewer"
        expected_expiry = datetime.now(timezone.utc) + timedelta(days=interview_confirmation.TOKEN_EXPIRY_DAYS)
        assert abs((token_row.expires_at - expected_expiry).total_seconds()) < 60


def test_propose_interview_slots_drops_slots_with_no_availability(db_session, tmp_path, monkeypatch):
    job_title = _unique_job_title("AllBusy")
    tracker_path = _setup_pool(tmp_path, job_title, "Busy Interviewer")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    interviewer = _make_interviewer(db_session, "Busy Interviewer")
    _connect_google(db_session, interviewer)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: False)
    monkeypatch.setattr(interview_confirmation, "send_email", lambda *a, **k: (_ for _ in ()).throw(AssertionError))

    result = interview_confirmation.propose_interview_slots(
        db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
        sender_refresh_token="sender-token", actor="recruiter@example.com",
    )

    assert result["slots_offered"] == 0
    assert result["tokens"] == []


def test_propose_interview_slots_rejects_candidate_without_email(db_session, tmp_path):
    job_title = _unique_job_title("NoEmail")
    tracker_path = _setup_pool(tmp_path, job_title, "Someone")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session, email=None)
    application = _make_application(db_session, job, candidate)

    try:
        interview_confirmation.propose_interview_slots(
            db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
            sender_refresh_token="sender-token", actor="recruiter@example.com",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_propose_interview_slots_invalidates_previous_live_proposal(db_session, tmp_path, monkeypatch):
    job_title = _unique_job_title("Reprop")
    tracker_path = _setup_pool(tmp_path, job_title, "Solo Interviewer")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    interviewer = _make_interviewer(db_session, "Solo Interviewer")
    _connect_google(db_session, interviewer)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    monkeypatch.setattr(interview_confirmation, "send_email", lambda *a, **k: "msg-id")

    first = interview_confirmation.propose_interview_slots(
        db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
        sender_refresh_token="sender-token", actor="recruiter@example.com",
    )
    interview_confirmation.propose_interview_slots(
        db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
        sender_refresh_token="sender-token", actor="recruiter@example.com",
    )

    first_tokens = (
        db_session.query(InterviewConfirmationToken)
        .filter(InterviewConfirmationToken.token.in_([t["token"] for t in first["tokens"]]))
        .all()
    )
    assert all(t.invalidated_at is not None for t in first_tokens)


# --- confirm_token: full lifecycle ---


def _propose(db_session, tmp_path, monkeypatch, job_title="Confirm", interviewer_name="Solo Interviewer"):
    job_title = _unique_job_title(job_title)
    tracker_path = _setup_pool(tmp_path, job_title, interviewer_name)
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    interviewer = _make_interviewer(db_session, interviewer_name)
    _connect_google(db_session, interviewer)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    monkeypatch.setattr(interview_confirmation, "send_email", lambda *a, **k: "msg-id")

    result = interview_confirmation.propose_interview_slots(
        db_session, application, tracker_path=str(tracker_path), candidate=candidate, job=job,
        sender_refresh_token="sender-token", actor="recruiter@example.com",
    )
    return application, candidate, interviewer, tracker_path, result


def test_confirm_token_success_advances_application_and_creates_event(db_session, tmp_path, monkeypatch):
    application, candidate, interviewer, tracker_path, result = _propose(db_session, tmp_path, monkeypatch)
    chosen = result["tokens"][0]

    monkeypatch.setattr(
        interview_confirmation,
        "create_calendar_event",
        lambda *a, **k: {"event_id": "evt123", "html_link": "https://calendar.google.com/evt123"},
    )

    outcome = interview_confirmation.confirm_token(db_session, chosen["token"])

    assert outcome.status == "confirmed"
    assert outcome.calendar_link == "https://calendar.google.com/evt123"
    db_session.refresh(application)
    assert application.status == "interview_scheduled"

    confirmed_row = (
        db_session.query(InterviewConfirmationToken)
        .filter(InterviewConfirmationToken.token == chosen["token"])
        .first()
    )
    assert confirmed_row.used_at is not None

    others = (
        db_session.query(InterviewConfirmationToken)
        .filter(
            InterviewConfirmationToken.application_id == application.id,
            InterviewConfirmationToken.token != chosen["token"],
        )
        .all()
    )
    assert len(others) == 2
    assert all(t.invalidated_at is not None for t in others)

    workbook = load_workbook(tracker_path)
    rows = list(workbook[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    header = [c.value for c in next(workbook[INTERVIEW_LOG_SHEET].iter_rows(min_row=1, max_row=1))]
    status_col = header.index("Status")
    confirmed_time_col = header.index("Final Scheduled Time")
    preferred_time_col = header.index("Candidate Preferred Time")
    matching = [r for r in rows if r[preferred_time_col] == chosen["slot_time"].isoformat()]
    assert len(matching) == 1
    assert matching[0][status_col] == "Confirmed"
    assert matching[0][confirmed_time_col] == chosen["slot_time"].isoformat()

    not_selected = [r for r in rows if r[status_col] == "Slot Not Selected by Candidate"]
    assert len(not_selected) == 2


def test_confirm_token_unknown_token_is_honest_not_an_error(db_session):
    outcome = interview_confirmation.confirm_token(db_session, "not-a-real-token")
    assert outcome.status == "invalid"


def test_confirm_token_already_used_is_reported_distinctly(db_session, tmp_path, monkeypatch):
    application, *_rest, result = _propose(db_session, tmp_path, monkeypatch)
    chosen = result["tokens"][0]
    monkeypatch.setattr(interview_confirmation, "create_calendar_event", lambda *a, **k: None)

    first = interview_confirmation.confirm_token(db_session, chosen["token"])
    second = interview_confirmation.confirm_token(db_session, chosen["token"])

    assert first.status == "confirmed"
    assert second.status == "used"


def test_confirm_token_invalidated_slot_is_reported_distinctly(db_session, tmp_path, monkeypatch):
    application, *_rest, result = _propose(db_session, tmp_path, monkeypatch)
    chosen = result["tokens"][0]
    other = result["tokens"][1]
    monkeypatch.setattr(interview_confirmation, "create_calendar_event", lambda *a, **k: None)

    interview_confirmation.confirm_token(db_session, chosen["token"])
    outcome = interview_confirmation.confirm_token(db_session, other["token"])

    assert outcome.status == "invalidated"


def test_confirm_token_expired_link_is_reported_distinctly(db_session, tmp_path, monkeypatch):
    application, *_rest, result = _propose(db_session, tmp_path, monkeypatch)
    chosen = result["tokens"][0]
    token_row = (
        db_session.query(InterviewConfirmationToken)
        .filter(InterviewConfirmationToken.token == chosen["token"])
        .first()
    )
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    outcome = interview_confirmation.confirm_token(db_session, chosen["token"])

    assert outcome.status == "expired"
    db_session.refresh(application)
    assert application.status == "hr_selected"  # never advanced


def test_confirm_token_missing_calendar_connection_still_confirms(db_session, tmp_path, monkeypatch):
    """A calendar event failure/absence must never block the confirmation itself -- same
    best-effort treatment as every other Google Calendar call in this app."""
    job_title = _unique_job_title("NoCal")
    tracker_path = _setup_pool(tmp_path, job_title, "Disconnected Interviewer")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    _make_interviewer(db_session, "Disconnected Interviewer")  # never connects Google

    # This interviewer has no Google connection, so select_interviewer would normally skip
    # them as "unknown availability" -- to isolate confirm_token's own resilience, insert a
    # token directly rather than going through propose_interview_slots.
    token_row = InterviewConfirmationToken(
        application_id=application.id, token="direct-token-no-cal", candidate_name=candidate.full_name,
        job_title=job.title, interviewer_name="Disconnected Interviewer", interviewer_user_id=None,
        slot_time=datetime.now(timezone.utc) + timedelta(days=1), duration_minutes=60,
        tracker_path=str(tracker_path), expires_at=datetime.now(timezone.utc) + timedelta(days=5),
    )
    db_session.add(token_row)
    db_session.commit()

    outcome = interview_confirmation.confirm_token(db_session, "direct-token-no-cal")

    assert outcome.status == "confirmed"
    assert outcome.calendar_link is None
    db_session.refresh(application)
    assert application.status == "interview_scheduled"


# --- HTTP layer ---


def test_propose_slots_endpoint_success(client, db_session, tmp_path, monkeypatch):
    job_title = _unique_job_title("HTTPPropose")
    tracker_path = _setup_pool(tmp_path, job_title, "Solo Interviewer")
    settings_row = db_session.get(InterviewSchedulingSettings, 1) or InterviewSchedulingSettings(id=1)
    settings_row.tracker_path = str(tracker_path)
    db_session.add(settings_row)
    db_session.commit()

    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    interviewer = _make_interviewer(db_session, "Solo Interviewer")
    _connect_google(db_session, interviewer)

    admin_user = db_session.query(User).filter(User.email == "test-admin@example.com").first()
    _connect_google(db_session, admin_user)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    monkeypatch.setattr(interview_confirmation, "send_email", lambda *a, **k: "msg-id")

    response = client.post(f"/interview-scheduling/applications/{application.id}/propose-slots")

    assert response.status_code == 200
    assert response.json()["slots_offered"] == 3


def test_propose_slots_endpoint_requires_hr_selected_status(client, db_session, tmp_path):
    job_title = _unique_job_title("WrongStatus")
    job = _make_job(db_session, job_title)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="received")

    response = client.post(f"/interview-scheduling/applications/{application.id}/propose-slots")
    assert response.status_code == 400


def test_propose_slots_endpoint_requires_tracker_configured(client, db_session):
    settings_row = db_session.get(InterviewSchedulingSettings, 1)
    if settings_row:
        settings_row.tracker_path = None
        db_session.commit()

    job = _make_job(db_session, _unique_job_title("NoTracker"))
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    response = client.post(f"/interview-scheduling/applications/{application.id}/propose-slots")
    assert response.status_code == 400


def test_propose_slots_endpoint_requires_auth(anonymous_client, db_session):
    job = _make_job(db_session, _unique_job_title("NoAuth"))
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    response = anonymous_client.post(f"/interview-scheduling/applications/{application.id}/propose-slots")
    assert response.status_code == 401


def test_interview_confirm_route_is_public_and_confirms(anonymous_client, db_session, tmp_path, monkeypatch):
    application, candidate, interviewer, tracker_path, result = _propose(db_session, tmp_path, monkeypatch)
    chosen = result["tokens"][0]
    monkeypatch.setattr(interview_confirmation, "create_calendar_event", lambda *a, **k: None)

    response = anonymous_client.get(f"/interview-confirm/{chosen['token']}")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "confirmed" in response.text.lower()


def test_interview_confirm_route_handles_unknown_token_honestly(anonymous_client):
    response = anonymous_client.get("/interview-confirm/totally-made-up-token")

    assert response.status_code == 200
    assert "isn't recognized" in response.text
