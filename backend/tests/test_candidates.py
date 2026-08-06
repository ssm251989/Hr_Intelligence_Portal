import io
import uuid

from docx import Document

from app.ai_services.resume_parser import ResumeParsingError
from app.models.audit_log import AuditLog


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
