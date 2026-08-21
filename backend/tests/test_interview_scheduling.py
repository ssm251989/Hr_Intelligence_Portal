import uuid
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook

from app.core.crypto import encrypt
from app.integrations.google_calendar import GoogleCalendarError, format_ist_datetime
from app.interview_scheduling import service as interview_scheduling_service
from app.interview_scheduling.tracker import (
    INTERVIEW_LOG_COLUMNS,
    INTERVIEW_LOG_SHEET,
    INTERVIEWER_POOL_COLUMNS,
    INTERVIEWER_POOL_SHEET,
    MAILS_COLUMNS,
    MAILS_SHEET,
    append_interview_log_row,
    ensure_tracker_file,
    eligible_interviewers_for_job,
    read_interviewer_pool,
    sync_interviewer_pool_job_titles,
)
from app.models.interview_scheduling_settings import InterviewSchedulingSettings
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration


def _unique_job_title(prefix: str) -> str:
    return f"{prefix} zzInterviewSched{uuid.uuid4().hex[:10]}"


def _make_job(db_session, title=None, status="published", **kwargs) -> JobRole:
    job = JobRole(title=title or _unique_job_title("Job"), status=status, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


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
    assert set(result["sheets_added"]) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET, MAILS_SHEET}
    assert path.exists()

    workbook = load_workbook(path)
    assert set(workbook.sheetnames) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET, MAILS_SHEET}
    pool_header = [cell.value for cell in next(workbook[INTERVIEWER_POOL_SHEET].iter_rows(min_row=1, max_row=1))]
    log_header = [cell.value for cell in next(workbook[INTERVIEW_LOG_SHEET].iter_rows(min_row=1, max_row=1))]
    mails_header = [cell.value for cell in next(workbook[MAILS_SHEET].iter_rows(min_row=1, max_row=1))]
    assert pool_header == INTERVIEWER_POOL_COLUMNS
    assert log_header == INTERVIEW_LOG_COLUMNS
    assert mails_header == MAILS_COLUMNS


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
    assert set(result["sheets_added"]) == {INTERVIEW_LOG_SHEET, MAILS_SHEET}

    reloaded = load_workbook(path)
    assert set(reloaded.sheetnames) == {INTERVIEWER_POOL_SHEET, INTERVIEW_LOG_SHEET, MAILS_SHEET}
    pool_rows = list(reloaded[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert pool_rows == [("Data Analyst", "Priya Nair")]  # untouched
    log_header = [cell.value for cell in next(reloaded[INTERVIEW_LOG_SHEET].iter_rows(min_row=1, max_row=1))]
    assert log_header == INTERVIEW_LOG_COLUMNS
    mails_header = [cell.value for cell in next(reloaded[MAILS_SHEET].iter_rows(min_row=1, max_row=1))]
    assert mails_header == MAILS_COLUMNS


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


# --- select_interviewer: date-based "Candidate Preferred Time", not a weekday name, in
# every branch (picked, no pool configured, all unavailable) ---


def test_select_interviewer_writes_date_based_preferred_time_when_picked(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("DateFormatPicked")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Solo Interviewer"])
    workbook.save(path)

    user = _make_user(db_session, "Solo Interviewer")
    _connect_google(db_session, user)
    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: True)
    preferred_time = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)

    interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title, preferred_time=preferred_time,
    )

    log_rows = list(load_workbook(path)[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert log_rows[-1][3] == format_ist_datetime(preferred_time)
    for weekday in ("Monday", "Mon,", "Wednesday"):
        assert weekday not in log_rows[-1][3]


def test_select_interviewer_writes_date_based_preferred_time_when_no_pool_configured(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("DateFormatNoPool")
    preferred_time = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)

    interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Jane Doe", job_title=job_title, preferred_time=preferred_time,
    )

    log_rows = list(load_workbook(path)[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert log_rows[-1][3] == format_ist_datetime(preferred_time)


def test_select_interviewer_writes_date_based_preferred_time_when_all_busy(db_session, tmp_path, monkeypatch):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    job_title = _unique_job_title("DateFormatAllBusy")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([job_title, "Person A"])
    workbook.save(path)

    user = _make_user(db_session, "Person A")
    _connect_google(db_session, user)
    monkeypatch.setattr(interview_scheduling_service, "check_calendar_availability", lambda *a, **k: False)
    preferred_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    interview_scheduling_service.select_interviewer(
        db_session, str(path), candidate_name="Nobody Free", job_title=job_title, preferred_time=preferred_time,
    )

    log_rows = list(load_workbook(path)[INTERVIEW_LOG_SHEET].iter_rows(min_row=2, values_only=True))
    assert log_rows[-1][3] == format_ist_datetime(preferred_time)
    assert log_rows[-1][3] == "28 Aug 2026, 05:30 PM IST"


# --- sync_interviewer_pool_job_titles ---


def test_sync_interviewer_pool_job_titles_adds_missing_rows_for_active_jobs(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    published_title = _unique_job_title("Published")
    ready_title = _unique_job_title("ReadyForPublishing")
    _make_job(db_session, title=published_title, status="published")
    _make_job(db_session, title=ready_title, status="ready_for_publishing")

    result = sync_interviewer_pool_job_titles(db_session, path)

    assert result["jobs_considered"] >= 2
    assert result["rows_added"] >= 2
    pool = read_interviewer_pool(path)
    assert pool[published_title] == []
    assert pool[ready_title] == []


def test_sync_interviewer_pool_job_titles_skips_draft_closed_and_on_hold_jobs(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    draft_title = _unique_job_title("Draft")
    closed_title = _unique_job_title("Closed")
    on_hold_title = _unique_job_title("OnHold")
    _make_job(db_session, title=draft_title, status="draft")
    _make_job(db_session, title=closed_title, status="closed")
    _make_job(db_session, title=on_hold_title, status="on_hold")

    sync_interviewer_pool_job_titles(db_session, path)

    pool = read_interviewer_pool(path)
    for title in (draft_title, closed_title, on_hold_title):
        assert title not in pool


def test_sync_interviewer_pool_job_titles_never_overwrites_existing_interviewer_list(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    title = _unique_job_title("AlreadyConfigured")
    _make_job(db_session, title=title, status="published")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([title, "Asha Rao, Vikram Singh"])
    workbook.save(path)

    sync_interviewer_pool_job_titles(db_session, path)

    pool = read_interviewer_pool(path)
    assert pool[title] == ["Asha Rao", "Vikram Singh"]
    rows = list(load_workbook(path)[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert len([r for r in rows if r[0] == title]) == 1  # no duplicate row added


def test_sync_interviewer_pool_job_titles_is_case_and_whitespace_insensitive(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    title = _unique_job_title("CaseInsensitive")
    _make_job(db_session, title=title, status="published")
    workbook = load_workbook(path)
    workbook[INTERVIEWER_POOL_SHEET].append([f"  {title.upper()}  ", "Someone"])
    workbook.save(path)

    sync_interviewer_pool_job_titles(db_session, path)

    rows = list(load_workbook(path)[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert len([r for r in rows if str(r[0]).strip().lower() == title.lower()]) == 1  # no duplicate row added


def test_sync_interviewer_pool_job_titles_never_deletes_row_for_a_now_closed_job(db_session, tmp_path):
    path = tmp_path / "tracker.xlsx"
    ensure_tracker_file(path)
    title = _unique_job_title("WasPublished")
    job = _make_job(db_session, title=title, status="published")

    sync_interviewer_pool_job_titles(db_session, path)
    assert title in read_interviewer_pool(path)

    # A recruiter fills in a real interviewer for this row before the job closes.
    workbook = load_workbook(path)
    for row in workbook[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2):
        if row[0].value == title:
            row[1].value = "Configured Interviewer"
    workbook.save(path)

    job.status = "closed"
    db_session.commit()

    sync_interviewer_pool_job_titles(db_session, path)

    pool = read_interviewer_pool(path)
    assert pool[title] == ["Configured Interviewer"]  # row and its data both survive


def test_sync_interviewer_pool_job_titles_creates_the_tracker_file_even_with_no_new_titles(tmp_path, db_session):
    # Mirrors app/local_import/job_folders.py's own
    # test_sync_job_folders_creates_the_roots_even_with_zero_active_jobs: the shared dev DB
    # this suite runs against always has some real published/ready_for_publishing jobs, so
    # this only asserts the function is safe to call and still creates the tracker file --
    # the "no active jobs at all" case isn't reachable against that shared DB.
    path = tmp_path / "tracker.xlsx"
    sync_interviewer_pool_job_titles(db_session, path)
    assert path.exists()


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

    # The Interviewer Pool sync (see sync_interviewer_pool_job_titles) may add rows for
    # whatever published/ready_for_publishing jobs the shared dev DB happens to have, but
    # must never touch this pre-existing row's own interviewer list.
    reloaded = load_workbook(path)
    rows = list(reloaded[INTERVIEWER_POOL_SHEET].iter_rows(min_row=2, values_only=True))
    assert ("Existing Role", "Existing Person") in rows
    assert len([r for r in rows if r[0] == "Existing Role"]) == 1


def test_put_interview_scheduling_settings_rejects_blank_path(client):
    response = client.put("/interview-scheduling/settings", json={"tracker_path": "   "})
    assert response.status_code == 422


def test_put_interview_scheduling_settings_syncs_interviewer_pool_for_published_jobs(client, db_session, tmp_path):
    path = tmp_path / "new-tracker.xlsx"
    title = _make_job(db_session, status="published").title

    response = client.put("/interview-scheduling/settings", json={"tracker_path": str(path)})

    assert response.status_code == 200
    body = response.json()
    assert body["interviewer_pool_rows_added"] >= 1
    assert body["interviewer_pool_jobs_considered"] >= 1
    pool = read_interviewer_pool(path)
    assert pool[title] == []


def test_interview_scheduling_settings_requires_auth(anonymous_client):
    response = anonymous_client.get("/interview-scheduling/settings")
    assert response.status_code == 401
