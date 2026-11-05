import io
import uuid

import pytest
from docx import Document

from app.ai_services.document_validator import DocumentValidationError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.bgv_document import BgvDocument
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_docx_bytes(text: str = "Aadhaar Number: 1234 5678 9012") -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_job(db_session) -> JobRole:
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session) -> Candidate:
    candidate = Candidate(full_name="Jane Doe")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="salary_approved") -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_document(db_session, application, doc_type="aadhaar", validation_status="pending", file_path=None):
    document = BgvDocument(
        application_id=application.id,
        doc_type=doc_type,
        validation_status=validation_status,
        file_path=file_path or f"{uuid.uuid4()}.docx",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


FAKE_VALID_RESULT = {
    "doc_type_detected": "aadhaar",
    "matches_expected_type": True,
    "extracted_fields": {"name": "Jane Doe", "id_number": "1234 5678 9012", "date": None},
    "validation_status": "valid",
    "issues": [],
}

FAKE_NEEDS_REVIEW_RESULT = {
    "doc_type_detected": "unknown",
    "matches_expected_type": False,
    "extracted_fields": {"name": None, "id_number": None, "date": None},
    "validation_status": "needs_review",
    "issues": ["OCR text too sparse to confirm document type"],
}


# --- /bgv/request -----------------------------------------------------------


def test_request_bgv_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="salary_approved")

    response = client.post(f"/applications/{application.id}/bgv/request")

    assert response.status_code == 200
    assert response.json()["status"] == "bgv_requested"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "bgv_requested")
        .one_or_none()
    )
    assert audit_entry is not None


def test_request_bgv_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="salary_ok")

    response = client.post(f"/applications/{application.id}/bgv/request")

    assert response.status_code == 400


def test_request_bgv_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/bgv/request")
    assert response.status_code == 404


# --- /bgv/documents upload ---------------------------------------------------


@pytest.mark.parametrize("doc_type", ["aadhaar", "pan", "degree", "experience"])
def test_upload_bgv_document_each_doc_type(client, db_session, doc_type):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": doc_type},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["doc_type"] == doc_type
    assert body["validation_status"] == "pending"

    db_session.refresh(application)
    assert application.status == "bgv_pending"


def test_upload_bgv_second_document_keeps_pending_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc1.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "pan"},
        files={"file": ("doc2.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    db_session.refresh(application)
    assert application.status == "bgv_pending"


def test_upload_bgv_document_image_placeholder_succeeds(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")

    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "pan"},
        files={"file": ("scan.png", b"not-a-real-png-but-that-is-fine", "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["doc_type"] == "pan"


def test_upload_bgv_document_wrong_application_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="received")

    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 400


def test_upload_bgv_document_invalid_doc_type_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "passport"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 400


def test_upload_bgv_document_unsupported_extension_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    response = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400


def test_upload_bgv_document_application_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 404


# --- GET /bgv/documents -------------------------------------------------------


def test_list_bgv_documents(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")
    doc1 = _make_document(db_session, application, doc_type="aadhaar")
    doc2 = _make_document(db_session, application, doc_type="pan")

    response = client.get(f"/applications/{application.id}/bgv/documents")

    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body} == {str(doc1.id), str(doc2.id)}


def test_list_bgv_documents_application_not_found(client):
    response = client.get(f"/applications/{uuid.uuid4()}/bgv/documents")
    assert response.status_code == 404


# --- validate ------------------------------------------------------------------


def test_validate_bgv_document_success(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.bgv.router.validate_document",
        lambda expected_doc_type, ocr_text: FAKE_VALID_RESULT,
    )

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")
    upload_resp = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    doc_id = upload_resp.json()["id"]

    response = client.post(f"/applications/{application.id}/bgv/documents/{doc_id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["validation_status"] == "valid"
    assert body["validator_output"] == FAKE_VALID_RESULT

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(doc_id), AuditLog.action == "ai_document_validator_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == FAKE_VALID_RESULT


def test_validate_bgv_document_needs_review_passthrough(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.bgv.router.validate_document",
        lambda expected_doc_type, ocr_text: FAKE_NEEDS_REVIEW_RESULT,
    )

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")
    upload_resp = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "pan"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    doc_id = upload_resp.json()["id"]

    response = client.post(f"/applications/{application.id}/bgv/documents/{doc_id}/validate")

    assert response.status_code == 200
    # 'needs_review' must be passed through exactly, never coerced to 'invalid'.
    assert response.json()["validation_status"] == "needs_review"


def test_validate_bgv_document_ai_failure_returns_502(client, db_session, monkeypatch):
    def fake_validate_document(expected_doc_type, ocr_text):
        raise DocumentValidationError("Failed to validate document: AI service timed out")

    monkeypatch.setattr("app.bgv.router.validate_document", fake_validate_document)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")
    upload_resp = client.post(
        f"/applications/{application.id}/bgv/documents",
        data={"doc_type": "aadhaar"},
        files={"file": ("doc.docx", _make_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    doc_id = upload_resp.json()["id"]

    response = client.post(f"/applications/{application.id}/bgv/documents/{doc_id}/validate")

    assert response.status_code == 502


def test_validate_bgv_document_not_found(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    response = client.post(f"/applications/{application.id}/bgv/documents/{uuid.uuid4()}/validate")

    assert response.status_code == 404


def test_validate_bgv_document_application_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/bgv/documents/{uuid.uuid4()}/validate")
    assert response.status_code == 404


# --- /bgv/clear ------------------------------------------------------------------


def test_clear_bgv_blocked_when_docs_not_all_valid(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")
    _make_document(db_session, application, doc_type="aadhaar", validation_status="valid")
    _make_document(db_session, application, doc_type="pan", validation_status="pending")

    response = client.post(f"/applications/{application.id}/bgv/clear", json={"decision": "clear"})

    assert response.status_code == 400
    assert "pan" in response.json()["detail"]


def test_clear_bgv_blocked_when_no_documents(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_requested")

    response = client.post(f"/applications/{application.id}/bgv/clear", json={"decision": "clear"})

    assert response.status_code == 400


def test_clear_bgv_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")
    _make_document(db_session, application, doc_type="aadhaar", validation_status="valid")
    _make_document(db_session, application, doc_type="pan", validation_status="valid")

    response = client.post(
        f"/applications/{application.id}/bgv/clear",
        json={"decision": "clear", "notes": "All docs verified", "cleared_by": "hr_jane"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "bgv_cleared"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "bgv_clearance_decision")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.actor == "hr_jane"
    assert audit_entry.details["decision"] == "clear"


def test_clear_bgv_reject(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")
    _make_document(db_session, application, doc_type="aadhaar", validation_status="needs_review")

    response = client.post(f"/applications/{application.id}/bgv/clear", json={"decision": "reject"})

    assert response.status_code == 200
    assert response.json()["status"] == "bgv_rejected"


def test_clear_bgv_defaults_actor_to_current_user_email(client, db_session, make_auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_pending")
    _make_document(db_session, application, doc_type="aadhaar", validation_status="valid")

    headers = make_auth_headers(role="recruiter", email="recruiter@example.com")
    client.post(f"/applications/{application.id}/bgv/clear", json={"decision": "clear"}, headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "bgv_clearance_decision")
        .one_or_none()
    )
    assert audit_entry.actor == "recruiter@example.com"


def test_clear_bgv_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared")

    response = client.post(f"/applications/{application.id}/bgv/clear", json={"decision": "clear"})

    assert response.status_code == 400


def test_clear_bgv_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/bgv/clear", json={"decision": "clear"})
    assert response.status_code == 404
