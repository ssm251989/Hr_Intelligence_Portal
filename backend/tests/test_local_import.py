import io
import uuid

from docx import Document

from app.local_import import service as local_import_service
from app.local_import import storage as local_import_storage
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _drop_in_inbox(filename: str, text: str) -> None:
    local_import_storage.ensure_directories()
    (local_import_storage.INBOX_DIR / filename).write_bytes(_make_docx_bytes(text))


def _unique_skill() -> str:
    # Isolates this test's own published job from the shared dev DB's real published jobs
    # (see test_suitability_service.py's identical comment) -- a uuid-based skill token can
    # never accidentally win/lose the pre-filter ranking against unrelated real jobs.
    return f"zzLocalImportTestSkill{uuid.uuid4().hex[:10]}"


def _fake_match_result(**overrides) -> dict:
    result = {
        "match_score": 80,
        "skill_match_pct": 80,
        "experience_score": 80,
        "location_score": 80,
        "certificates_score": 80,
        "missing_skills": [],
        "recommendation": "strong_fit",
    }
    result.update(overrides)
    return result


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


def _make_candidate(db_session, **kwargs) -> Candidate:
    candidate = Candidate(full_name=kwargs.pop("full_name", "Jane Doe"), **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


# --- find_duplicate_candidate: pure DB query, no AI ---


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
    found = local_import_service.find_duplicate_candidate(db_session, "Priya Verma", 4.0, "Chennai, India")
    assert found is None


def test_find_duplicate_candidate_no_match_when_experience_differs(db_session):
    _make_candidate(
        db_session, full_name="Priya Sharma", location="Chennai, India",
        parsed_fields={"total_experience_years": 4.0},
    )
    found = local_import_service.find_duplicate_candidate(db_session, "Priya Sharma", 7.0, "Chennai, India")
    assert found is None


def test_find_duplicate_candidate_no_match_when_location_differs(db_session):
    _make_candidate(
        db_session, full_name="Priya Sharma", location="Chennai, India",
        parsed_fields={"total_experience_years": 4.0},
    )
    found = local_import_service.find_duplicate_candidate(db_session, "Priya Sharma", 4.0, "Mumbai, India")
    assert found is None


def test_find_duplicate_candidate_missing_signal_never_matches(db_session):
    _make_candidate(
        db_session, full_name="Priya Sharma", location=None,
        parsed_fields={"total_experience_years": 4.0},
    )
    # A resume with no extractable location must never be treated as a duplicate of
    # anyone, even a candidate whose own location also happens to be null.
    assert local_import_service.find_duplicate_candidate(db_session, "Priya Sharma", 4.0, None) is None


# --- run_local_import_scan: integration, real filesystem + fake Anthropic client ---


def test_scan_with_empty_inbox_reports_zero_and_logs(db_session):
    result = local_import_service._run_scan(db_session, "test-actor")
    assert result["files_found"] == 0
    assert result["imported"] == 0

    started = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "local_import_run", AuditLog.action == "local_import_run_started")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert started is not None
    assert started.details["files_found"] == 0


def test_scan_creates_candidate_and_application_for_the_ai_suggested_job(db_session, monkeypatch):
    skill = _unique_skill()
    job = JobRole(title="Backend Engineer", status="published", jd_text="Needs the skill.", skills=[skill])
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    monkeypatch.setattr("app.screening.suitability.match_resume", lambda *a, **k: _fake_match_result())
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_match_result())

    resume_text = f"Resume for a candidate with skill {skill}."
    _drop_in_inbox("candidate_a.docx", resume_text)
    _install_fake_client(
        monkeypatch, {resume_text: _parsed(full_name="Local Import Candidate", experience=3.0, skills=[skill])}
    )

    result = local_import_service._run_scan(db_session, "test-actor")
    assert result["imported"] == 1
    assert result["duplicates"] == 0
    assert result["no_suitable_job"] == 0
    assert result["failed"] == 0

    candidate = db_session.query(Candidate).filter(Candidate.full_name == "Local Import Candidate").one()
    assert candidate.source == "local_import"
    assert candidate.location == "Bangalore, India"
    assert candidate.suitable_job_id == job.id

    application = db_session.query(Application).filter(Application.candidate_id == candidate.id).one()
    assert application.job_role_id == job.id

    # The file must be moved out of the inbox into the archive, tagged "imported".
    assert not (local_import_storage.INBOX_DIR / "candidate_a.docx").exists()
    archived = list(local_import_storage.ARCHIVE_DIR.glob("*_imported_candidate_a.docx"))
    assert len(archived) == 1

    completed_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "candidate", AuditLog.entity_id == candidate.id, AuditLog.action == "local_import_completed")
        .one()
    )
    assert completed_entry.details["application_id"] == str(application.id)


def test_scan_skips_creating_a_candidate_for_an_exact_duplicate(db_session, monkeypatch):
    existing = _make_candidate(
        db_session, full_name="Existing Candidate", location="Pune, India",
        parsed_fields={"total_experience_years": 6.0},
    )
    resume_text = "Resume text for a duplicate."
    _drop_in_inbox("dup.docx", resume_text)
    _install_fake_client(
        monkeypatch,
        {resume_text: _parsed(full_name="Existing Candidate", experience=6.0, location="Pune, India")},
    )

    before_candidate_count = db_session.query(Candidate).count()
    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["duplicates"] == 1
    assert result["imported"] == 0
    assert db_session.query(Candidate).count() == before_candidate_count

    assert not (local_import_storage.INBOX_DIR / "dup.docx").exists()
    archived = list(local_import_storage.ARCHIVE_DIR.glob("*_duplicate_dup.docx"))
    assert len(archived) == 1

    dup_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "local_import_run", AuditLog.action == "local_import_duplicate_skipped")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert dup_entry is not None
    assert dup_entry.details["matched_candidate_id"] == str(existing.id)


def test_scan_creates_candidate_with_no_application_when_no_suitable_job(db_session, monkeypatch):
    # The shared dev DB always has SOME real published job with jd_text (see
    # test_suitability_service.py's own comments on this), so pre_filter_published_jobs is
    # never truly empty here -- what actually needs forcing is every one of those
    # comparisons failing, so attempt_auto_suggest_suitable_job's own "best_job stays None"
    # path is what's under test, not an empty pre-filter.
    from app.ai_services.resume_matcher import ResumeMatchError

    def _always_fails(*args, **kwargs):
        raise ResumeMatchError("no real AI call in this test")

    monkeypatch.setattr("app.screening.suitability.match_resume", _always_fails)

    skill = _unique_skill()
    resume_text = f"Resume mentioning nothing but {skill}, which no job asks for."
    _drop_in_inbox("no_job.docx", resume_text)
    _install_fake_client(
        monkeypatch, {resume_text: _parsed(full_name="Unmatched Candidate", experience=2.0, skills=[skill])}
    )

    result = local_import_service._run_scan(db_session, "test-actor")
    assert result["no_suitable_job"] == 1
    assert result["imported"] == 0

    candidate = db_session.query(Candidate).filter(Candidate.full_name == "Unmatched Candidate").one()
    assert candidate.suitable_job_id is None
    assert db_session.query(Application).filter(Application.candidate_id == candidate.id).count() == 0

    archived = list(local_import_storage.ARCHIVE_DIR.glob("*_no-suitable-job_no_job.docx"))
    assert len(archived) == 1


def test_scan_archives_a_failed_batch_result_without_creating_a_candidate(db_session, monkeypatch):
    resume_text = "This resume will fail to parse."
    _drop_in_inbox("broken.docx", resume_text)
    _install_fake_client(monkeypatch, {resume_text: "error"})

    before_candidate_count = db_session.query(Candidate).count()
    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["failed"] == 1
    assert result["imported"] == 0
    assert db_session.query(Candidate).count() == before_candidate_count
    assert not (local_import_storage.INBOX_DIR / "broken.docx").exists()
    assert len(list(local_import_storage.ARCHIVE_DIR.glob("*_failed_broken.docx"))) == 1


def test_scan_archives_an_unsupported_file_type_without_ever_calling_the_ai(db_session, monkeypatch):
    local_import_storage.ensure_directories()
    (local_import_storage.INBOX_DIR / "notes.txt").write_bytes(b"not a real resume file type")
    fake_client = _install_fake_client(monkeypatch, {})

    result = local_import_service._run_scan(db_session, "test-actor")

    # notes.txt isn't in ALLOWED_EXTENSIONS at all, so it's never even picked up as a file
    # to process -- files_found only counts pdf/docx.
    assert result["files_found"] == 0
    assert fake_client.messages.batches.create_call_count == 0
    assert (local_import_storage.INBOX_DIR / "notes.txt").exists()  # left alone, not a resume


def test_scan_processes_multiple_files_in_one_batch_submission(db_session, monkeypatch):
    from app.ai_services.resume_matcher import ResumeMatchError

    def _always_fails(*args, **kwargs):
        raise ResumeMatchError("no real AI call in this test")

    # Forces both candidates to "no suitable job" deterministically (see the previous
    # test's comment) -- this test's actual point is the single shared batch submission,
    # not suitability matching itself.
    monkeypatch.setattr("app.screening.suitability.match_resume", _always_fails)

    text_a = "First candidate resume text."
    text_b = "Second candidate resume text."
    _drop_in_inbox("a.docx", text_a)
    _drop_in_inbox("b.docx", text_b)
    fake_client = _install_fake_client(
        monkeypatch,
        {
            text_a: _parsed(full_name="Candidate A", experience=1.0, location="Delhi, India"),
            text_b: _parsed(full_name="Candidate B", experience=2.0, location="Delhi, India"),
        },
    )

    result = local_import_service._run_scan(db_session, "test-actor")

    assert result["files_found"] == 2
    assert result["no_suitable_job"] == 2  # no published job set up in this test
    assert fake_client.messages.batches.create_call_count == 1  # ONE batch, not two calls
    assert len(fake_client.messages.batches.last_requests) == 2


def test_run_local_import_scan_opens_and_closes_its_own_db_session(monkeypatch):
    # The public entry point (used by both the scheduler and the manual-trigger endpoint)
    # must work with no request/session available at all -- unlike _run_scan's tests above,
    # this doesn't receive a db_session fixture.
    result = local_import_service.run_local_import_scan(actor="test-actor")
    assert "files_found" in result


# --- POST /local-import/run-now ---


def test_run_now_endpoint_triggers_a_real_scan_and_returns_its_summary(client):
    response = client.post("/local-import/run-now")
    assert response.status_code == 200
    body = response.json()
    assert "files_found" in body
    assert "run_id" in body


def test_run_now_endpoint_requires_auth(anonymous_client):
    response = anonymous_client.post("/local-import/run-now")
    assert response.status_code == 401
