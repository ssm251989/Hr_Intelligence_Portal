import uuid
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook

from app.core.crypto import encrypt
from app.integrations.google_calendar import GoogleCalendarError
from app.interview_scheduling import service as interview_scheduling_service
from app.interview_scheduling.tracker import (
    INTERVIEW_LOG_COLUMNS,
    INTERVIEW_LOG_SHEET,
    INTERVIEWER_POOL_COLUMNS,
    INTERVIEWER_POOL_SHEET,
    append_interview_log_row,
    ensure_tracker_file,
    eligible_interviewers_for_job,
    read_interviewer_pool,
)
from app.models.interview_scheduling_settings import InterviewSchedulingSettings
from app.models.user import User
from app.models.user_integration import UserIntegration


def _unique_job_title(prefix: str) -> str:
    return f"{prefix} zzInterviewSched{uuid.uuid4().hex[:10]}"


def _make_user(db_session, name, role="interviewer", **kwargs) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name=name, role=role, **kwargs
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


# --- ensure_tracker_file: fresh file ---


def test_ensure_tracker_file_creates_fresh_file_with_expected_sheets_and_columns(tmp_path):
    path = tmp_path / "tracker.xlsx"

    result = ensure_tracker_file(path)

    assert result["created"] is True
    assert set(result["sheets_added"]) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET}
    assert path.exists()

    workbook = load_workbook(path)
    assert set(workbook.sheetnames) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET}
    pool_header = [cell.value for cell in next(workbook[INTERVIEWER_POOL_SHEET].iter_rows(min_row=1, max_row=1))]
    log_header = [cell.value for cell in next(workbook[INTERVIEW_LOG_SHEET].iter_rows(min_row=1, max_row=1))]
    assert pool_header == INTERVIEWER_POOL_COLUMNS
    assert log_header == INTERVIEW_LOG_COLUMNS


def test_ensure_tracker_file_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "tracker.xlsx"
    result = ensure_tracker_file(path)
    assert result["created"] is True
    assert path.exists()


# --- ensure_tracker_file: existing file is never overwritten ---


def test_ensure_tracker_file_never_overwrites_existing_valid_file(tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)

    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append(["Backend Engineer", "Asha Rao, Vikram Singh"])
    workbook.save(path)

    result = ensure_tracker_file(path)

    assert result["created"] is False
    assert result["sheets_added"] == []
    assert result["columns_added"] == {}

    reloaded = load_workbook(path)
    rows = list(reloaded[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert rows == [("Backend Engineer", "Asha Rao, Vikram Singh")]  # untouched


def test_ensure_tracker_file_adds_missing_sheet_without_touching_the_other(tmp_path):
    path = tmp_path / "tracker.xlsx"
    workbook = Workbook()
    default_sheet = workbook.active
    pool_sheet = workbook.create_sheet(INTERVIEWER_POOL_SHEET)
    pool_sheet.append(INTERVIEWER_POOL_COLUMNS)
    pool_sheet.append(["Data Analyst", "Priya Nair"])
    workbook.remove(default_sheet)
    workbook.save(path)

    result = ensure_tracker_file(path)

    assert result["created"] is False
    assert result["sheets_added"] == [INTERVIEW_LOG_SHEET]

    reloaded = load_workbook(path)
    assert set(reloaded.sheetnames) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET}
    pool_rows = list(reloaded[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert pool_rows == [("Data Analyst", "Priya Nair")]  # untouched
    log_header = [cell.value for cell in next(reloaded[INTERVIEW_LOG_SHEET].iter_rows(min_row=1, max_row=1))]
    assert log_header == INTERVIEW_LOG_COLUMNS


def test_ensure_tracker_file_adds_missing_columns_to_end_of_existing_header(tmp_path):
    path = tmp_path / "tracker.xlsx"
    workbook = Workbook()
    default_sheet = workbook.active
    log_sheet = workbook.create_sheet(INTERVIEW_LOG_SHEET)
    # A partial, hand-created header missing the last two real columns.
    log_sheet.append(["Candidate", "Job Title", "Assigned Interviewer"])
    log_sheet.append(["Jane Doe", "Backend Engineer", "Asha Rao"])
    pool_sheet = workbook.create_sheet(INTERVIEWER_POOL_SHEET)
    pool_sheet.append(INTERVIEWER_POOL_COLUMNS)
    workbook.remove(default_sheet)
    workbook.save(path)

    result = ensure_tracker_file(path)

    assert result["created"] is False
    assert INTERVIEW_LOG_SHEET in result["columns_added"]
    missing_expected = [c for c in INTERVIEW_LOG_COLUMNS if c not in ("Candidate", "Job Title", "Assigned Interviewer")]
    assert result["columns_added"][INTERVIEW_LOG_SHEET] == missing_expected

    reloaded = load_workbook(path)
    sheet = reloaded[INTERVIEW_LOG_SHEET]
    new_header = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    assert new_header[:3] == ["Candidate", "Job Title", "Assigned Interviewer"]
    assert set(new_header) == set(INTERVIEW_LOG_COLUMNS)
    # The existing data row is completely untouched -- still just its original 3 values.
    data_row = list(sheet.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    assert data_row[:3] == ("Jane Doe", "Backend Engineer", "Asha Rao")


# --- Interviewer Pool reading/parsing ---


def test_read_interviewer_pool_parses_comma_separated_names(tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append(["Backend Engineer", " Asha Rao ,Vikram Singh,  ,Priya Nair"])
    workbook.save(path)

    pool = read_interviewer_pool(path)

    assert pool["Backend Engineer"] == ["Asha Rao", "Vikram Singh", "Priya Nair"]


def test_eligible_interviewers_for_job_matches_case_and_whitespace_insensitively(tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append(["  Backend Engineer  ", "Asha Rao, Vikram Singh"])
    workbook.save(path)

    assert eligible_interviewers_for_job(path, "backend engineer") == ["Asha Rao", "Vikram Singh"]
    assert eligible_interviewers_for_job(path, "BACKEND ENGINEER") == ["Asha Rao", "Vikram Singh"]


def test_eligible_interviewers_for_job_returns_empty_for_unknown_job(tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    assert eligible_interviewers_for_job(path, "Nonexistent Role") == []


def test_append_interview_log_row_appends_without_touching_existing_rows(tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    append_interview_log_row(path, {"Candidate": "First", "Job Title": "Backend Engineer", "Status": "No Interviewer Available"})
    append_interview_log_row(path, {"Candidate": "Second", "Job Title": "Backend Engineer", "Status": "Interviewer Selected -- Awaiting Confirmation"})

    workbook = load_workbook(path)
    rows = list(workbook[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 2
    assert rows[0][0] == "First"
    assert rows[1][0] == "Second"


# --- select_interviewer: random pick with retry ---


def test_select_interviewer_picks_the_only_available_interviewer(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("Backend")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Solo Interviewer"])
    workbook.save(path)

    user = _make_user(db_session, "Solo Interviewer")
    _connect_google(db_session, user)
    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] == "Solo Interviewer"
    assert result["reason"] is None
    assert result["attempts"][-1]["outcome"] == "picked"

    log_rows = list(load_workbook(path)[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert log_rows[-1][0] == "Jane Doe"
    assert log_rows[-1][2] == "Solo Interviewer"
    assert log_rows[-1][7] == "Interviewer Selected -- Awaiting Confirmation"


def test_select_interviewer_retries_a_different_interviewer_on_conflict(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("Retry")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Busy Person, Free Person"])
    workbook.save(path)

    busy_user = _make_user(db_session, "Busy Person")
    _connect_google(db_session, busy_user)
    free_user = _make_user(db_session, "Free Person")
    _connect_google(db_session, free_user)

    # Both interviewers' fake tokens decrypt to the same literal string, so distinguishing
    # them by call order (not token value) is what's actually unambiguous here.
    calls = []

    def fake_availability_ordered(refresh_token, start, end):
        calls.append(refresh_token)
        return len(calls) > 1  # first call busy, second call free

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", fake_availability_ordered)

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="John Roe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc),
    )

    assert len(calls) == 2  # tried both -- proves the retry actually happened
    assert result["assigned_interviewer"] in ("Busy Person", "Free Person")
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["outcome"] == "skipped_busy"
    assert result["attempts"][1]["outcome"] == "picked"


def test_select_interviewer_reports_total_unavailability_when_all_busy(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("AllBusy")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Person A, Person B"])
    workbook.save(path)

    for name in ("Person A", "Person B"):
        user = _make_user(db_session, name)
        _connect_google(db_session, user)

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: False)

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Nobody Free", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] is None
    assert result["reason"] == interview_scheduling_service.ALL_UNAVAILABLE
    assert len(result["attempts"]) == 2
    assert all(a["outcome"] == "skipped_busy" for a in result["attempts"])

    log_rows = list(load_workbook(path)[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert log_rows[-1][0] == "Nobody Free"
    assert log_rows[-1][7] == "No Interviewer Available"


def test_select_interviewer_skips_unregistered_names(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("Unregistered")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Nobody In The System"])
    workbook.save(path)

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] is None
    assert result["attempts"][0]["outcome"] == "skipped_not_registered"


def test_select_interviewer_treats_unconnected_google_as_unknown_availability_and_skips(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("Unconnected")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "No Google Person"])
    workbook.save(path)

    _make_user(db_session, "No Google Person")  # registered, but never connected Google

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] is None
    assert result["attempts"][0]["outcome"] == "skipped_unknown_availability"
    assert "not connected" in result["attempts"][0]["reason"]


def test_select_interviewer_treats_calendar_check_failure_as_unknown_availability(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("CalendarError")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Error Person"])
    workbook.save(path)

    user = _make_user(db_session, "Error Person")
    _connect_google(db_session, user)

    def fake_raise(*args, **kwargs):
        raise GoogleCalendarError("boom")

    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", fake_raise)

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] is None
    assert result["attempts"][0]["outcome"] == "skipped_unknown_availability"
    assert "Could not check" in result["attempts"][0]["reason"]


def test_select_interviewer_reports_when_no_pool_configured_for_job(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("NoPool")

    result = interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title,
        preferred_time=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert result["assigned_interviewer"] is None
    assert result["reason"] == interview_scheduling_service.NO_POOL_CONFIGURED
    assert result["attempts"] == []


# --- GET/PUT /interview-scheduling/settings ---


def test_get_interview_scheduling_settings_defaults_to_unconfigured(client, db_session):
    settings_row = db_session.get(InterviewSchedulingSettings, 1)
    settings_row.tracker_path = None
    db_session.commit()

    response = client.get("/interview-scheduling/settings")
    assert response.status_code == 200
    assert response.json()["tracker_path"] is None


def test_put_interview_scheduling_settings_creates_tracker_file(client, tmp_path):
    path = tmp_path / "new-tracker.xlsx"

    response = client.put("/interview-scheduling/settings", json={"tracker_path": str(path)})

    assert response.status_code == 200
    body = response.json()
    assert body["tracker_path"] == str(path)
    assert body["validation"]["created"] is True
    assert path.exists()


def test_put_interview_scheduling_settings_never_overwrites_existing_tracker(client, tmp_path):
    path = tmp_path / "existing-tracker.xlsx"
    ensure_tracker_file(path)
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append(["Existing Role", "Existing Person"])
    workbook.save(path)

    response = client.put("/interview-scheduling/settings", json={"tracker_path": str(path)})

    assert response.status_code == 200
    assert response.json()["validation"]["created"] is False

    reloaded = load_workbook(path)
    rows = list(reloaded[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert rows == [("Existing Role", "Existing Person")]


def test_put_interview_scheduling_settings_rejects_blank_path(client):
    response = client.put("/interview-scheduling/settings", json={"tracker_path": "   "})
    assert response.status_code == 422


def test_interview_scheduling_settings_requires_auth(anonymous_client):
    response = anonymous_client.get("/interview-scheduling/settings")
    assert response.status_code == 401
