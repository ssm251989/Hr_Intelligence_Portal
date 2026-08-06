import io
import uuid

from docx import Document

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


def _make_job(db_session, title="Public QA Engineer", status="published", **kwargs) -> JobRole:
    job = JobRole(
        title=title,
        status=status,
        department=kwargs.get("department", "Engineering"),
        location=kwargs.get("location", "Remote"),
        experience_level=kwargs.get("experience_level", "Mid"),
        skills=kwargs.get("skills", ["Python", "Testing"]),
        jd_text=kwargs.get("jd_text", "We are hiring a QA engineer..."),
        salary_band_min=kwargs.get("salary_band_min", 900000),
        salary_band_max=kwargs.get("salary_band_max", 1400000),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# --- GET /public/jobs ---------------------------------------------------------


def test_list_public_jobs_only_shows_published(anonymous_client, db_session):
    published = _make_job(db_session, title="Published Role", status="published")
    _make_job(db_session, title="Draft Role", status="draft")
    _make_job(db_session, title="Ready Role", status="ready_for_publishing")
    _make_job(db_session, title="Closed Role", status="closed")

    response = anonymous_client.get("/public/jobs")

    assert response.status_code == 200
    titles = [job["title"] for job in response.json()]
    assert titles == ["Published Role"]
    assert response.json()[0]["id"] == str(published.id)


def test_list_public_jobs_excludes_internal_fields(anonymous_client, db_session):
    _make_job(db_session, title="Public Fields Role", status="published")

    response = anonymous_client.get("/public/jobs")

    body = response.json()[0]
    assert set(body.keys()) == {"id", "title", "department", "location", "experience_level", "skills", "jd_text"}
    assert "salary_band_min" not in body
    assert "salary_band_max" not in body
    assert "created_by" not in body
    assert "hiring_manager_id" not in body


def test_list_public_jobs_empty_when_none_published(anonymous_client, db_session):
    _make_job(db_session, title="Draft Only", status="draft")

    response = anonymous_client.get("/public/jobs")

    assert response.status_code == 200
    assert response.json() == []


# --- GET /public/jobs/{id} -----------------------------------------------------


def test_get_public_job_detail_success(anonymous_client, db_session):
    job = _make_job(db_session, title="Detail Role", status="published")

    response = anonymous_client.get(f"/public/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["title"] == "Detail Role"
    assert "salary_band_min" not in body


def test_get_public_job_detail_draft_returns_404(anonymous_client, db_session):
    job = _make_job(db_session, title="Draft Detail Role", status="draft")

    response = anonymous_client.get(f"/public/jobs/{job.id}")

    assert response.status_code == 404


def test_get_public_job_detail_closed_returns_404(anonymous_client, db_session):
    job = _make_job(db_session, title="Closed Detail Role", status="closed")

    response = anonymous_client.get(f"/public/jobs/{job.id}")

    assert response.status_code == 404


def test_get_public_job_detail_nonexistent_returns_404(anonymous_client):
    response = anonymous_client.get(f"/public/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


# --- POST /public/apply --------------------------------------------------------


def test_submit_application_success(anonymous_client, db_session):
    job = _make_job(db_session, title="Apply Role", status="published")
    resume_bytes = _make_docx_bytes("Jordan Applicant\njordan@example.com")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Jordan Applicant", "email": "jordan@example.com", "phone": "555-0100"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "received"
    application_id = uuid.UUID(body["application_id"])

    application = db_session.get(Application, application_id)
    assert application is not None
    assert application.job_role_id == job.id
    assert application.status == "received"

    candidate = db_session.get(Candidate, application.candidate_id)
    assert candidate.full_name == "Jordan Applicant"
    assert candidate.email == "jordan@example.com"
    assert candidate.phone == "555-0100"
    assert candidate.resume_path

    audit_actions = (
        db_session.query(AuditLog.action)
        .filter(AuditLog.entity_id.in_([application.id, candidate.id]))
        .all()
    )
    assert ("candidate_uploaded",) in audit_actions
    assert ("application_created",) in audit_actions


def test_submit_application_without_phone(anonymous_client, db_session):
    job = _make_job(db_session, title="No Phone Role", status="published")
    resume_bytes = _make_docx_bytes("No Phone Applicant")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "No Phone Applicant", "email": "nophone@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201


def test_submit_application_schedules_background_resume_parsing(anonymous_client, db_session, monkeypatch):
    # The background task opens its own DB session/connection (deliberately -- it must
    # outlive the request), so it can't see this test's not-yet-committed transaction.
    # Assert the scheduling contract instead: the right candidate_id gets handed to the
    # background parser. The parsing logic itself (extract -> AI parse -> apply to
    # candidate) is the same parse_and_apply_resume already covered by
    # test_candidates.py::test_parse_resume_updates_parsed_fields.
    captured = {}

    def fake_background_parse(candidate_id):
        captured["candidate_id"] = candidate_id

    monkeypatch.setattr("app.public.router._parse_resume_in_background", fake_background_parse)

    job = _make_job(db_session, title="Background Parse Role", status="published")
    resume_bytes = _make_docx_bytes("Some Applicant\nsome@example.com")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Some Applicant", "email": "some@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    application_id = uuid.UUID(response.json()["application_id"])
    application = db_session.get(Application, application_id)

    assert captured["candidate_id"] == application.candidate_id


def test_submit_application_against_unpublished_job_returns_404(anonymous_client, db_session):
    job = _make_job(db_session, title="Draft Apply Role", status="draft")
    resume_bytes = _make_docx_bytes("Applicant")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Applicant", "email": "applicant@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 404


def test_submit_application_against_nonexistent_job_returns_404(anonymous_client):
    resume_bytes = _make_docx_bytes("Applicant")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(uuid.uuid4()), "full_name": "Applicant", "email": "applicant@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 404


def test_submit_application_rejects_unsupported_file_type(anonymous_client, db_session):
    job = _make_job(db_session, title="Bad File Role", status="published")

    response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Applicant", "email": "applicant@example.com"},
        files={"resume": ("resume.txt", b"plain text resume", "text/plain")},
    )

    assert response.status_code == 400


def test_submit_application_no_candidate_created_when_job_rejected(anonymous_client, db_session):
    job = _make_job(db_session, title="Rejected Apply Role", status="draft")
    resume_bytes = _make_docx_bytes("Applicant")
    before_count = db_session.query(Candidate).count()

    anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Applicant", "email": "applicant@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert db_session.query(Candidate).count() == before_count


# --- No-auth-required contract -------------------------------------------------


def test_public_endpoints_require_no_authentication(anonymous_client, db_session):
    job = _make_job(db_session, title="No Auth Role", status="published")
    resume_bytes = _make_docx_bytes("Applicant")

    list_response = anonymous_client.get("/public/jobs")
    detail_response = anonymous_client.get(f"/public/jobs/{job.id}")
    apply_response = anonymous_client.post(
        "/public/apply",
        data={"job_id": str(job.id), "full_name": "Applicant", "email": "applicant@example.com"},
        files={"resume": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert list_response.status_code != 401
    assert detail_response.status_code != 401
    assert apply_response.status_code != 401


def test_other_endpoints_still_require_authentication(anonymous_client):
    assert anonymous_client.get("/jobs").status_code == 401
    assert anonymous_client.get("/candidates").status_code == 401
    assert anonymous_client.get("/applications").status_code == 401
