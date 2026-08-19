import io
import uuid
from datetime import date

import pytest
from docx import Document

from app.local_import import job_folders
from app.local_import import scheduler as local_import_scheduler
from app.local_import import service as local_import_service
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.local_import_settings import LocalImportSettings


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _unique_title(prefix: str) -> str:
    # Isolates this test's own job(s) from the shared dev DB's real jobs -- match_folder_to_
    # job scans every job in the whole table, so a uuid-based title guarantees no accidental
    # collision (see test_suitability_service.py's identical reasoning).
    return f"{prefix} zzLocalImport{uuid.uuid4().hex[:10]}"


def _make_job(db_session, title=None, status="published", jd_text="Job description text.", **kwargs) -> JobRole:
    job = JobRole(title=title or _unique_title("Job"), status=status, jd_text=jd_text, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, **kwargs) -> Candidate:
    candidate = Candidate(full_name=kwargs.pop("full_name", "Jane Doe"), **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


@pytest.fixture()
def configured_roots(db_session, tmp_path):
    """Points local_import_settings' singleton row at a fresh tmp_path pair -- isolated the
    same way every other DB row is in this suite (db_session's own rolled-back
    transaction), so no autouse filesystem monkeypatch is needed."""
    ready = tmp_path / "ready-to-upload"
    already = tmp_path / "already-uploaded"
    settings_row = db_session.get(LocalImportSettings, 1)
    settings_row.ready_to_upload_root = str(ready)
    settings_row.already_uploaded_root = str(already)
    db_session.commit()
    return ready, already


def _parsed(full_name="Jane Doe", experience=5.0, location="Bangalore, India", **overrides) -> dict:
    parsed = {
        "full_name": full_name,
        "email": "jane@example.com",
        "phone": "1234567890",
        "location": location,
        "total_experience_years": experience,
        "skills": [],
        "education": [],
        "work_history": [],
        "certificates": [],
    }
    parsed.update(overrides)
    return parsed


# --- Fake Anthropic client: real request/response shape, no network/AI call ---


class _FakeToolUseBlock:
    def __init__(self, tool_input):
        self.type = "tool_use"
        self.name = "record_parsed_resume"
        self.input = tool_input


class _FakeMessage:
    def __init__(self, tool_input):
        self.content = [_FakeToolUseBlock(tool_input)]


class _FakeResult:
    def __init__(self, type_, message=None):
        self.type = type_
        self.message = message


class _FakeIndividualResponse:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


class _FakeBatch:
    def __init__(self, batch_id):
        self.id = batch_id
        self.processing_status = "ended"


class _FakeBatches:
    """text_to_output maps a resume's raw extracted text to either a parsed-fields dict
    (-> a succeeded batch result) or the string "error" (-> an errored batch result)."""

    def __init__(self, text_to_output: dict):
        self.text_to_output = text_to_output
        self.last_requests = []
        self.create_call_count = 0

    def create(self, requests):
        self.last_requests = list(requests)
        self.create_call_count += 1
        return _FakeBatch("test-batch-id")

    def retrieve(self, batch_id):
        return _FakeBatch(batch_id)

    def results(self, batch_id):
        out = []
        for req in self.last_requests:
            content = req["params"]["messages"][0]["content"]
            text = content.removeprefix("Resume text:\n")
            outcome = self.text_to_output.get(text, "error")
            if outcome == "error":
                out.append(_FakeIndividualResponse(req["custom_id"], _FakeResult("errored")))
            else:
                out.append(_FakeIndividualResponse(req["custom_id"], _FakeResult("succeeded", _FakeMessage(outcome))))
        return out


class _FakeMessagesNamespace:
    def __init__(self, batches):
        self.batches = batches


class _FakeAnthropicClient:
    def __init__(self, text_to_output: dict):
        self.messages = _FakeMessagesNamespace(_FakeBatches(text_to_output))


def _install_fake_client(monkeypatch, text_to_output: dict) -> _FakeAnthropicClient:
    fake_client = _FakeAnthropicClient(text_to_output)
    monkeypatch.setattr(local_import_service, "_get_client", lambda: fake_client)
    return fake_client


def _fail_suitability(monkeypatch):
    # attempt_auto_suggest_suitable_job still runs as a side effect of parse_and_apply_
    # resume (Part B is unaffected by this redesign) -- forcing every comparison to fail
    # keeps these tests deterministic and free of real AI calls regardless of the shared
    # dev DB's other real published jobs, without changing what's actually under test here
    # (the folder-based job assignment, not Suitable-For).
    from app.ai_services.resume_matcher import ResumeMatchError

    def _always_fails(*args, **kwargs):
        raise ResumeMatchError("no real AI call in this test")

    monkeypatch.setattr("app.screening.suitability.match_resume", _always_fails)


# --- find_duplicate_candidate: pure DB query, no AI (unchanged by this redesign) ---


def test_find_duplicate_candidate_exact_match(db_session):
    existing = _make_candidate(
        db_session, full_name="Priya Sharma", location="Chennai, India",
        parsed_fields={"total_experience_years": 4.0},
    )
    found = local_import_service.find_duplicate_candidate(db_session, "Priya Sharma", 4.0, "Chennai, India")
    assert found is not None
    assert found.id == existing.id


def test_find_duplicate_candidate_case_and_whitespace_insensitive(db_session):
    existing = _make_candidate(
        db_session, full_name="Priya Sharma", location="Chennai, India",
        parsed_fields={"total_experience_years": 4.0},
    )
    found = local_import_service.find_duplicate_candidate(db_session, "  priya SHARMA  ", 4.0, "  chennai, india ")
    assert found is not None
    assert found.id == existing.id


def test_find_duplicate_candidate_no_match_when_name_differs(db_session):
    _make_candidate(
        db_session, full_name="Priya Sharma", location="Chennai, India",
        parsed_fields={"total_experience_years": 4.0},
    )
    assert local_import_service.find_duplicate_candidate(db_session, "Priya Verma", 4.0, "Chennai, India") is None


def test_find_duplicate_candidate_missing_signal_never_matches(db_session):
    _make_candidate(
        db_session, full_name="Priya Sharma", location=None,
        parsed_fields={"total_experience_years": 4.0},
    )
    assert local_import_service.find_duplicate_candidate(db_session, "Priya Sharma", 4.0, None) is None


# --- sanitize_job_folder_name: pure function ---


def test_sanitize_job_folder_name_replaces_invalid_characters():
    assert job_folders.sanitize_job_folder_name('Sr. Dev: "Backend"/API') == "Sr. Dev_ _Backend__API"


def test_sanitize_job_folder_name_collapses_whitespace():
    assert job_folders.sanitize_job_folder_name("Backend   Engineer\t\tII") == "Backend Engineer II"


def test_sanitize_job_folder_name_strips_trailing_dot_and_space():
    assert job_folders.sanitize_job_folder_name("Backend Engineer . ") == "Backend Engineer"


def test_sanitize_job_folder_name_never_returns_empty():
    assert job_folders.sanitize_job_folder_name("...") == "untitled-job"


# --- match_folder_to_job ---


def test_match_folder_to_job_finds_the_right_job(db_session):
    title = _unique_title("Match")
    job = _make_job(db_session, title=title)
    found = job_folders.match_folder_to_job(db_session, job_folders.sanitize_job_folder_name(title))
    assert found is not None
    assert found.id == job.id


def test_match_folder_to_job_returns_none_when_no_job_matches(db_session):
    assert job_folders.match_folder_to_job(db_session, f"NoSuchJob{uuid.uuid4().hex[:10]}") is None


def test_match_folder_to_job_returns_none_when_ambiguous(db_session):
    # Two distinct jobs whose titles sanitize to the exact same folder name -- must never
    # guess which one a file in that folder is for.
    shared = _unique_title("Ambiguous")
    _make_job(db_session, title=f"{shared}.")  # trailing dot is stripped by sanitization
    _make_job(db_session, title=shared)
    folder_name = job_folders.sanitize_job_folder_name(shared)
    assert job_folders.match_folder_to_job(db_session, folder_name) is None


def test_match_folder_to_job_matches_jobs_regardless_of_status(db_session):
    # A folder for a job that's since closed must still match -- only folder *creation* is
    # gated to published/ready_for_publishing (see sync_job_folders tests below).
    title = _unique_title("Closed")
    job = _make_job(db_session, title=title, status="closed")
    found = job_folders.match_folder_to_job(db_session, job_folders.sanitize_job_folder_name(title))
    assert found is not None
    assert found.id == job.id


# --- sync_job_folders ---


def test_sync_job_folders_creates_missing_subfolders_under_both_roots(db_session, tmp_path):
    ready = tmp_path / "ready"
    already = tmp_path / "already"
    published_title = _unique_title("Published")
    ready_title = _unique_title("ReadyForPublishing")
    _make_job(db_session, title=published_title, status="published")
    _make_job(db_session, title=ready_title, status="ready_for_publishing")

    result = job_folders.sync_job_folders(db_session, ready, already)

    assert result["jobs_considered"] >= 2
    assert result["folders_created"] >= 4  # 2 jobs x 2 roots, at minimum
    for root in (ready, already):
        assert (root / job_folders.sanitize_job_folder_name(published_title)).is_dir()
        assert (root / job_folders.sanitize_job_folder_name(ready_title)).is_dir()


def test_sync_job_folders_skips_draft_and_closed_and_on_hold_jobs(db_session, tmp_path):
    ready = tmp_path / "ready"
    already = tmp_path / "already"
    draft_title = _unique_title("Draft")
    closed_title = _unique_title("Closed")
    on_hold_title = _unique_title("OnHold")
    _make_job(db_session, title=draft_title, status="draft")
    _make_job(db_session, title=closed_title, status="closed")
    _make_job(db_session, title=on_hold_title, status="on_hold")

    job_folders.sync_job_folders(db_session, ready, already)

    for title in (draft_title, closed_title, on_hold_title):
        assert not (ready / job_folders.sanitize_job_folder_name(title)).exists()
        assert not (already / job_folders.sanitize_job_folder_name(title)).exists()


def test_sync_job_folders_never_deletes_an_existing_folder_for_a_now_inactive_job(db_session, tmp_path):
    ready = tmp_path / "ready"
    already = tmp_path / "already"
    title = _unique_title("WasPublished")
    job = _make_job(db_session, title=title, status="published")

    job_folders.sync_job_folders(db_session, ready, already)
    folder_name = job_folders.sanitize_job_folder_name(title)
    assert (ready / folder_name).is_dir()

    # A file a recruiter hasn't moved out yet -- must survive the job closing.
    marker = ready / folder_name / "in_progress_resume.docx"
    marker.write_bytes(b"placeholder")

    job.status = "closed"
    db_session.commit()

    job_folders.sync_job_folders(db_session, ready, already)

    assert (ready / folder_name).is_dir()
    assert marker.exists()


def test_sync_job_folders_creates_the_roots_even_with_zero_active_jobs(tmp_path, db_session):
    ready = tmp_path / "ready-empty"
    already = tmp_path / "already-empty"
    job_folders.sync_job_folders(db_session, ready, already)
    assert ready.is_dir()
    assert already.is_dir()


# --- move_to_already_uploaded: rename-with-date-on-move ---


def test_move_to_already_uploaded_renames_with_date_and_same_named_subfolder(tmp_path):
    from app.local_import.storage import move_to_already_uploaded

    already_root = tmp_path / "already"
    source = tmp_path / "resume.docx"
    source.write_bytes(b"placeholder")

    destination = move_to_already_uploaded(source, "Backend Engineer", already_root, date(2026, 8, 19))

    assert not source.exists()
    assert destination == already_root / "Backend Engineer" / "resume_2026-08-19.docx"
    assert destination.exists()


def test_move_to_already_uploaded_avoids_collision_across_different_dates(tmp_path):
    from app.local_import.storage import move_to_already_uploaded

    already_root = tmp_path / "already"
    first = tmp_path / "resume.docx"
    first.write_bytes(b"first")
    move_to_already_uploaded(first, "Backend Engineer", already_root, date(2026, 8, 19))

    second = tmp_path / "resume.docx"
    second.write_bytes(b"second, a resubmission the next day")
    destination = move_to_already_uploaded(second, "Backend Engineer", already_root, date(2026, 8, 20))

    assert destination == already_root / "Backend Engineer" / "resume_2026-08-20.docx"
    first_copy = already_root / "Backend Engineer" / "resume_2026-08-19.docx"
    assert first_copy.exists()
    assert first_copy.read_bytes() == b"first"
    assert destination.read_bytes() == b"second, a resubmission the next day"


# --- run_local_import_scan: not configured ---


def test_scan_reports_not_configured_when_roots_are_unset(db_session):
    # Explicitly unset -- this is a real, shared singleton row (real recruiters, or this
    # test file's own other tests via the /local-import/settings endpoint, may have
    # configured it for real outside this test's own transaction), so this test cannot
    # assume it starts out null; it must make that state true itself.
    settings_row = db_session.get(LocalImportSettings, 1)
    settings_row.ready_to_upload_root = None
    settings_row.already_uploaded_root = None
    db_session.commit()

    result = local_import_service._run_scan(db_session, "test-actor")
    assert result["configured"] is False
    assert result["totals"]["files_found"] == 0

    started = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "local_import_run", AuditLog.action == "local_import_run_started")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert started.details["configured"] is False


# --- run_local_import_scan: folder-to-job matching + processing ---


def test_scan_matches_folder_to_job_and_creates_application_against_it_not_ai_guessed(
    db_session, configured_roots, monkeypatch
):
    _fail_suitability(monkeypatch)
    ready_root, already_root = configured_roots
    title = _unique_title("Backend")
    job = _make_job(db_session, title=title)
    folder_name = job_folders.sanitize_job_folder_name(title)
    (ready_root / folder_name).mkdir(parents=True)

    resume_text = "Resume for a backend candidate."
    (ready_root / folder_name / "candidate.docx").write_bytes(_make_docx_bytes(resume_text))
    _install_fake_client(
        monkeypatch, {resume_text: _parsed(full_name="Folder Match Candidate", experience=4.0, location="Pune, India")}
    )

    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["totals"]["imported"] == 1
    assert result["per_folder"][folder_name]["job_id"] == str(job.id)
    assert result["per_folder"][folder_name]["imported"] == 1

    candidate = db_session.query(Candidate).filter(Candidate.full_name == "Folder Match Candidate").one()
    application = db_session.query(Application).filter(Application.candidate_id == candidate.id).one()
    # The applied-for job is the one the FOLDER matched -- never candidate.suitable_job_id
    # (forced to stay null above by _fail_suitability), proving job assignment doesn't
    # depend on the AI-guessed Suitable-For path at all anymore.
    assert application.job_role_id == job.id
    assert candidate.suitable_job_id is None

    assert not (ready_root / folder_name / "candidate.docx").exists()
    moved = list((already_root / folder_name).glob("candidate_*.docx"))
    assert len(moved) == 1


def test_scan_skips_and_logs_a_folder_with_no_matching_job_leaving_the_file_in_place(
    db_session, configured_roots, monkeypatch
):
    ready_root, already_root = configured_roots
    stray_folder = ready_root / "Some Renamed Or Typo Job"
    stray_folder.mkdir(parents=True)
    (stray_folder / "orphan.docx").write_bytes(_make_docx_bytes("An orphaned resume."))
    fake_client = _install_fake_client(monkeypatch, {})

    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["totals"]["skipped_no_matching_job"] == 1
    assert result["unmatched_folders"]["Some Renamed Or Typo Job"]["files_skipped"] == 1
    # Never even reaches the AI -- a folder with no matching job is resolved locally, before
    # any batch submission.
    assert fake_client.messages.batches.create_call_count == 0

    # Left in place for manual attention -- never moved, never deleted. sync_job_folders
    # still creates subfolders under already_root for every OTHER real active job in the
    # shared dev DB (unrelated to this test), so only this specific stray folder name is
    # asserted absent there, not the whole root.
    assert (stray_folder / "orphan.docx").exists()
    assert not (already_root / "Some Renamed Or Typo Job").exists()

    skipped_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "local_import_run", AuditLog.action == "local_import_skipped_no_matching_job")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert skipped_entry.details["filename"] == "orphan.docx"
    assert skipped_entry.details["folder"] == "Some Renamed Or Typo Job"


def test_scan_handles_multiple_job_folders_with_per_folder_breakdown(db_session, configured_roots, monkeypatch):
    _fail_suitability(monkeypatch)
    ready_root, already_root = configured_roots

    title_a = _unique_title("JobA")
    title_b = _unique_title("JobB")
    job_a = _make_job(db_session, title=title_a)
    job_b = _make_job(db_session, title=title_b)
    folder_a = job_folders.sanitize_job_folder_name(title_a)
    folder_b = job_folders.sanitize_job_folder_name(title_b)
    (ready_root / folder_a).mkdir(parents=True)
    (ready_root / folder_b).mkdir(parents=True)

    text_a = "Resume for job A's candidate."
    text_b = "Resume for job B's candidate."
    (ready_root / folder_a / "a.docx").write_bytes(_make_docx_bytes(text_a))
    (ready_root / folder_b / "b.docx").write_bytes(_make_docx_bytes(text_b))
    _install_fake_client(
        monkeypatch,
        {
            text_a: _parsed(full_name="Candidate A", experience=1.0, location="Delhi, India"),
            text_b: _parsed(full_name="Candidate B", experience=2.0, location="Mumbai, India"),
        },
    )

    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["totals"]["imported"] == 2
    assert result["per_folder"][folder_a]["job_id"] == str(job_a.id)
    assert result["per_folder"][folder_a]["imported"] == 1
    assert result["per_folder"][folder_b]["job_id"] == str(job_b.id)
    assert result["per_folder"][folder_b]["imported"] == 1

    app_a = (
        db_session.query(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .filter(Candidate.full_name == "Candidate A")
        .one()
    )
    app_b = (
        db_session.query(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .filter(Candidate.full_name == "Candidate B")
        .one()
    )
    assert app_a.job_role_id == job_a.id
    assert app_b.job_role_id == job_b.id


# --- duplicate detection still works in the new folder-based flow ---


def test_scan_skips_creating_a_candidate_for_an_exact_duplicate_in_the_matched_folder(
    db_session, configured_roots, monkeypatch
):
    ready_root, already_root = configured_roots
    title = _unique_title("DupJob")
    job = _make_job(db_session, title=title)
    folder_name = job_folders.sanitize_job_folder_name(title)
    (ready_root / folder_name).mkdir(parents=True)

    existing = _make_candidate(
        db_session, full_name="Existing Candidate", location="Chennai, India",
        parsed_fields={"total_experience_years": 6.0},
    )

    resume_text = "Resume text for a duplicate."
    (ready_root / folder_name / "dup.docx").write_bytes(_make_docx_bytes(resume_text))
    _install_fake_client(
        monkeypatch,
        {resume_text: _parsed(full_name="Existing Candidate", experience=6.0, location="Chennai, India")},
    )

    before_candidate_count = db_session.query(Candidate).count()
    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["totals"]["duplicates"] == 1
    assert result["totals"]["imported"] == 0
    assert result["per_folder"][folder_name]["job_id"] == str(job.id)
    assert db_session.query(Candidate).count() == before_candidate_count

    # A decided outcome (duplicate) still moves out of ready-to-upload, same as "imported".
    assert not (ready_root / folder_name / "dup.docx").exists()
    moved = list((already_root / folder_name).glob("dup_*.docx"))
    assert len(moved) == 1

    dup_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "local_import_run", AuditLog.action == "local_import_duplicate_skipped")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert dup_entry.details["matched_candidate_id"] == str(existing.id)
    assert dup_entry.details["folder"] == folder_name


def test_scan_leaves_a_genuine_parse_failure_in_place(db_session, configured_roots, monkeypatch):
    ready_root, already_root = configured_roots
    title = _unique_title("FailJob")
    _make_job(db_session, title=title)
    folder_name = job_folders.sanitize_job_folder_name(title)
    (ready_root / folder_name).mkdir(parents=True)

    resume_text = "This resume will fail to parse."
    (ready_root / folder_name / "broken.docx").write_bytes(_make_docx_bytes(resume_text))
    _install_fake_client(monkeypatch, {resume_text: "error"})

    before_candidate_count = db_session.query(Candidate).count()
    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["totals"]["failed"] == 1
    assert db_session.query(Candidate).count() == before_candidate_count
    assert (ready_root / folder_name / "broken.docx").exists()  # left in place, not moved


def test_run_local_import_scan_opens_and_closes_its_own_db_session():
    # The public entry point (used by both the scheduler and the manual-trigger endpoint)
    # must work with no request/session available at all.
    result = local_import_service.run_local_import_scan(actor="test-actor")
    assert "configured" in result


def test_run_now_endpoint_triggers_a_real_scan_and_returns_its_summary(client):
    response = client.post("/local-import/run-now")
    assert response.status_code == 200
    assert "configured" in response.json()


def test_run_now_endpoint_requires_auth(anonymous_client):
    response = anonymous_client.post("/local-import/run-now")
    assert response.status_code == 401


# --- GET/PUT /local-import/settings ---


def test_get_settings_returns_unconfigured_state_by_default(client, db_session):
    settings_row = db_session.get(LocalImportSettings, 1)
    settings_row.ready_to_upload_root = None
    settings_row.already_uploaded_root = None
    db_session.commit()

    response = client.get("/local-import/settings")
    assert response.status_code == 200
    assert response.json()["ready_to_upload_root"] is None
    assert response.json()["already_uploaded_root"] is None


def test_put_settings_saves_paths_and_syncs_job_folders_immediately(client, db_session, tmp_path):
    ready = tmp_path / "ready-via-api"
    already = tmp_path / "already-via-api"
    title = _unique_title("ApiSync")
    _make_job(db_session, title=title, status="published")

    response = client.put(
        "/local-import/settings",
        json={
            "ready_to_upload_root": str(ready),
            "already_uploaded_root": str(already),
            "scan_interval_minutes": 30,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ready_to_upload_root"] == str(ready)
    assert body["already_uploaded_root"] == str(already)
    assert body["scan_interval_minutes"] == 30
    assert body["jobs_considered"] >= 1
    assert body["folders_created"] >= 2

    assert (ready / job_folders.sanitize_job_folder_name(title)).is_dir()
    assert (already / job_folders.sanitize_job_folder_name(title)).is_dir()


def test_put_settings_rejects_blank_path(client):
    response = client.put(
        "/local-import/settings",
        json={"ready_to_upload_root": "   ", "already_uploaded_root": "/tmp/x", "scan_interval_minutes": 30},
    )
    assert response.status_code == 422


def test_get_settings_requires_auth(anonymous_client):
    response = anonymous_client.get("/local-import/settings")
    assert response.status_code == 401


# --- scan_interval_minutes: configurable scheduler interval ---


def test_get_settings_defaults_scan_interval_to_thirty_minutes(client, db_session):
    settings_row = db_session.get(LocalImportSettings, 1)
    settings_row.scan_interval_minutes = 30
    db_session.commit()

    response = client.get("/local-import/settings")
    assert response.status_code == 200
    assert response.json()["scan_interval_minutes"] == 30


@pytest.mark.parametrize("bad_interval", [4, 1441, 0, -5])
def test_put_settings_rejects_scan_interval_outside_bounds(client, bad_interval):
    response = client.put(
        "/local-import/settings",
        json={
            "ready_to_upload_root": "/tmp/ready-bounds",
            "already_uploaded_root": "/tmp/already-bounds",
            "scan_interval_minutes": bad_interval,
        },
    )
    assert response.status_code == 422


def test_put_settings_saves_scan_interval_and_returns_it(client, tmp_path):
    response = client.put(
        "/local-import/settings",
        json={
            "ready_to_upload_root": str(tmp_path / "ready"),
            "already_uploaded_root": str(tmp_path / "already"),
            "scan_interval_minutes": 45,
        },
    )
    assert response.status_code == 200
    assert response.json()["scan_interval_minutes"] == 45


def test_put_settings_reschedules_the_live_scheduler_without_a_restart(client, tmp_path):
    # `client`'s TestClient runs this app's real lifespan (see app/main.py), so a real
    # BackgroundScheduler is already running with whatever interval was configured when it
    # started -- proving the save takes effect on THAT running instance, not merely on the
    # next process start, is the whole point of this test.
    job_before = local_import_scheduler._scheduler.get_job(local_import_scheduler.JOB_ID)
    assert job_before is not None

    response = client.put(
        "/local-import/settings",
        json={
            "ready_to_upload_root": str(tmp_path / "ready"),
            "already_uploaded_root": str(tmp_path / "already"),
            "scan_interval_minutes": 45,
        },
    )
    assert response.status_code == 200

    job_after = local_import_scheduler._scheduler.get_job(local_import_scheduler.JOB_ID)
    assert job_after.trigger.interval.total_seconds() == 45 * 60


def test_reschedule_scan_interval_is_a_noop_with_no_running_scheduler():
    # Called outside the app's lifespan (e.g. directly, as here) -- must never raise just
    # because this process hasn't started its own scheduler.
    assert local_import_scheduler._scheduler is None
    local_import_scheduler.reschedule_scan_interval(45)  # no exception
