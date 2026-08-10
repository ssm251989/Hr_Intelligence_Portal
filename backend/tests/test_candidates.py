import io
import uuid

from docx import Document

from app.ai_services.resume_parser import ResumeParsingError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session, title="CSV Test Job", **kwargs) -> JobRole:
    job = JobRole(title=title, **kwargs)
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


def _make_application(db_session, job, candidate, status="received", **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_upload_resume_creates_candidate(client):
    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["resume_path"]
    assert body["parsed_fields"] is None


def test_upload_resume_rejects_unsupported_type(client):
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.txt", b"plain text resume", "text/plain")},
    )

    assert response.status_code == 400


def test_get_candidate_not_found(client):
    response = client.get(f"/candidates/{uuid.uuid4()}")
    assert response.status_code == 404


def test_download_resume(client):
    resume_bytes = _make_docx_bytes("Jane Doe")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.get(f"/candidates/{candidate_id}/resume")

    assert response.status_code == 200
    assert response.content == resume_bytes


def test_parse_resume_updates_parsed_fields(client, db_session, monkeypatch):
    fake_parsed = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "total_experience_years": 4.5,
        "skills": ["Python", "SQL"],
        "education": [{"degree": "B.Tech", "institution": "IIT", "year": 2019}],
        "work_history": [{"company": "Acme", "title": "Engineer", "start": "2020", "end": "2024"}],
    }
    monkeypatch.setattr("app.candidates.router.parse_resume", lambda raw_text: fake_parsed)

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    body = response.json()
    assert body["parsed_fields"] == fake_parsed

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_id == uuid.UUID(candidate_id),
            AuditLog.action == "ai_resume_parser_scored",
        )
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == fake_parsed


def test_parse_resume_ai_failure_returns_502(client, monkeypatch):
    def fake_parse_resume(raw_text):
        raise ResumeParsingError("Failed to parse resume: AI service timed out")

    monkeypatch.setattr("app.candidates.router.parse_resume", fake_parse_resume)

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 502


def test_parse_resume_without_upload_returns_400(client, db_session):
    from app.models.candidate import Candidate

    candidate = Candidate(full_name="No Resume")
    db_session.add(candidate)
    db_session.commit()

    response = client.post(f"/candidates/{candidate.id}/parse-resume")

    assert response.status_code == 400


# --- source tracking ---


def test_upload_resume_sets_manual_source(client):
    resume_bytes = _make_docx_bytes("Jane Doe")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    assert response.json()["source"] == "manual"


def test_candidate_read_includes_location_defaulting_to_null(client, db_session):
    candidate = _make_candidate(db_session, full_name="No Location")

    response = client.get(f"/candidates/{candidate.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["location"] is None
    assert body["source"] == "manual"


# --- GET /candidates/applications (Candidates List page data source) ---


def test_list_candidate_applications_one_row_per_application(client, db_session):
    job_a = _make_job(db_session, title="Job A")
    job_b = _make_job(db_session, title="Job B")
    candidate = _make_candidate(db_session, full_name="Multi Applicant", email="multi@example.com")
    app_a = _make_application(db_session, job_a, candidate, status="received")
    app_b = _make_application(db_session, job_b, candidate, status="screened", match_score=77)

    response = client.get("/candidates/applications", params={"search": "multi@example.com", "page_size": 50})

    assert response.status_code == 200
    body = response.json()
    ids = {row["application_id"] for row in body["items"]}
    assert str(app_a.id) in ids
    assert str(app_b.id) in ids
    by_id = {row["application_id"]: row for row in body["items"]}
    assert by_id[str(app_b.id)]["match_score"] == 77.0
    assert by_id[str(app_b.id)]["job_title"] == "Job B"


def test_list_candidate_applications_filters_by_status_source_and_job(client, db_session):
    job = _make_job(db_session, title="Filter Job")
    portal_candidate = _make_candidate(db_session, full_name="Portal Cand", source="career_portal")
    manual_candidate = _make_candidate(db_session, full_name="Manual Cand", source="manual")
    portal_app = _make_application(db_session, job, portal_candidate, status="screened")
    _make_application(db_session, job, manual_candidate, status="received")

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "status": "screened", "source": "career_portal", "page_size": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["application_id"] == str(portal_app.id)


def test_list_candidate_applications_pagination(client, db_session):
    job = _make_job(db_session, title="Pagination Job")
    candidate = _make_candidate(db_session, full_name="Pagination Cand")
    for _ in range(5):
        _make_application(db_session, job, candidate)

    first_page = client.get(
        "/candidates/applications", params={"job_role_id": str(job.id), "page": 1, "page_size": 2}
    ).json()
    second_page = client.get(
        "/candidates/applications", params={"job_role_id": str(job.id), "page": 2, "page_size": 2}
    ).json()

    assert first_page["total"] == 5
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert {row["application_id"] for row in first_page["items"]}.isdisjoint(
        {row["application_id"] for row in second_page["items"]}
    )


# --- POST /candidates/import-csv ---


def test_import_csv_creates_real_candidates(client):
    csv_bytes = (
        b"name,email,phone,resume\n"
        b"Alice Import,alice.import@example.com,1234567890,https://example.com/alice.pdf\n"
        b"Bob Import,bob.import@example.com,,\n"
    )

    response = client.post(
        "/candidates/import-csv", files={"file": ("candidates.csv", csv_bytes, "text/csv")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert len(body["imported_candidate_ids"]) == 2

    alice = client.get(f"/candidates/{body['imported_candidate_ids'][0]}").json()
    assert alice["source"] == "csv_import"


def test_import_csv_stores_http_resume_link_but_ignores_bare_filename(client):
    csv_bytes = (
        b"name,email,resume\n"
        b"Has Link,haslink@example.com,https://example.com/resume.pdf\n"
        b"No Link,nolink@example.com,resume.pdf\n"
    )

    response = client.post("/candidates/import-csv", files={"file": ("c.csv", csv_bytes, "text/csv")})
    ids = response.json()["imported_candidate_ids"]

    candidates = {c["email"]: c for c in [client.get(f"/candidates/{i}").json() for i in ids]}
    assert candidates["haslink@example.com"]["resume_path"] == "https://example.com/resume.pdf"
    assert candidates["nolink@example.com"]["resume_path"] is None


def test_import_csv_skips_rows_missing_name_or_email(client):
    csv_bytes = b"name,email\nOnly Name,\n,onlyemail@example.com\nComplete Row,complete@example.com\n"

    response = client.post("/candidates/import-csv", files={"file": ("c.csv", csv_bytes, "text/csv")})

    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    assert all("Missing required" in err["reason"] for err in body["errors"])


def test_import_csv_skips_invalid_email(client):
    csv_bytes = b"name,email\nBad Email,not-an-email\n"

    response = client.post("/candidates/import-csv", files={"file": ("c.csv", csv_bytes, "text/csv")})

    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert "Invalid email" in body["errors"][0]["reason"]


def test_import_csv_skips_duplicate_email_within_file_and_against_existing(client, db_session):
    _make_candidate(db_session, full_name="Existing", email="existing@example.com")

    csv_bytes = (
        b"name,email\n"
        b"Dup One,dup@example.com\n"
        b"Dup Two,dup@example.com\n"
        b"Already Exists,existing@example.com\n"
    )

    response = client.post("/candidates/import-csv", files={"file": ("c.csv", csv_bytes, "text/csv")})

    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    reasons = " ".join(err["reason"] for err in body["errors"])
    assert "Duplicate email in this file" in reasons
    assert "already exists" in reasons


def test_import_csv_rejects_non_csv_file(client):
    response = client.post(
        "/candidates/import-csv", files={"file": ("candidates.txt", b"name,email\nA,a@example.com\n", "text/plain")}
    )
    assert response.status_code == 400


def test_import_csv_matches_header_aliases_case_insensitively(client):
    csv_bytes = b"Full Name,Email Address,Mobile\nAlias Cand,alias@example.com,999\n"

    response = client.post("/candidates/import-csv", files={"file": ("c.csv", csv_bytes, "text/csv")})

    body = response.json()
    assert body["imported"] == 1
    candidate = client.get(f"/candidates/{body['imported_candidate_ids'][0]}").json()
    assert candidate["full_name"] == "Alias Cand"
    assert candidate["phone"] == "999"
