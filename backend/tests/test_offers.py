import uuid

from app.core.crypto import encrypt
from app.integrations.docusign import DocuSignError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.user import User
from app.models.user_integration import UserIntegration

FAKE_OFFER_RESULT = {
    "offer_letter_text": "Dear Jane Doe, we are pleased to offer you the role of Backend Engineer...",
    "key_terms_summary": {
        "role": "Backend Engineer",
        "salary": "1300000.0",
        "start_date": "2026-09-01",
        "reporting_manager": "John Smith",
    },
}


def _make_job(db_session, hiring_manager_id=None) -> JobRole:
    job = JobRole(title="Backend Engineer", hiring_manager_id=hiring_manager_id)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, full_name="Jane Doe", email=None) -> Candidate:
    candidate = Candidate(full_name=full_name, email=email)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(
    db_session, job, candidate, status="bgv_cleared", approved_salary=None, expected_salary=None
) -> Application:
    application = Application(
        job_role_id=job.id,
        candidate_id=candidate.id,
        status=status,
        approved_salary=approved_salary,
        expected_salary=expected_salary,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_hiring_manager(db_session, full_name="John Smith") -> User:
    user = User(email="manager@example.com", hashed_password="x", role="hiring_manager", full_name=full_name)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_offer(
    db_session,
    application,
    offer_letter_text="Existing letter",
    signed=False,
    onboarding_status="not_started",
    docusign_envelope_id=None,
    docusign_sender_id=None,
):
    offer = Offer(
        application_id=application.id,
        offer_letter_text=offer_letter_text,
        signed=signed,
        onboarding_status=onboarding_status,
        docusign_envelope_id=docusign_envelope_id,
        docusign_sender_id=docusign_sender_id,
    )
    db_session.add(offer)
    db_session.commit()
    db_session.refresh(offer)
    return offer


def _connect_docusign(db_session, user) -> UserIntegration:
    integration = UserIntegration(user_id=user.id, provider="docusign", refresh_token=encrypt("refresh-token"))
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def _get_test_admin(db_session) -> User:
    return db_session.query(User).filter(User.email == "test-admin@example.com").one()


# --- /offer/generate ---------------------------------------------------------


def test_generate_offer_success(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.offers.router.generate_offer_letter",
        lambda **kwargs: FAKE_OFFER_RESULT,
    )

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["offer_letter_text"] == FAKE_OFFER_RESULT["offer_letter_text"]
    assert body["signed"] is False
    assert body["onboarding_status"] == "not_started"

    db_session.refresh(application)
    assert application.status == "offer_sent"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_offer_letter_generated")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == FAKE_OFFER_RESULT


def test_generate_offer_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 400


def test_generate_offer_missing_salary_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="bgv_cleared", approved_salary=None, expected_salary=None
    )

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 400


def test_generate_offer_missing_candidate_name_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, full_name=None)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 400


def test_generate_offer_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/offer/generate",
        json={"start_date": "2026-09-01"},
    )
    assert response.status_code == 404


def test_generate_offer_salary_fallback_uses_expected_salary_when_approved_is_null(client, db_session, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return FAKE_OFFER_RESULT

    monkeypatch.setattr("app.offers.router.generate_offer_letter", fake_generate)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="bgv_cleared", approved_salary=None, expected_salary=1100000
    )

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    assert captured["approved_salary"] == "1100000.0"


def test_generate_offer_uses_approved_salary_over_expected_when_both_set(client, db_session, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return FAKE_OFFER_RESULT

    monkeypatch.setattr("app.offers.router.generate_offer_letter", fake_generate)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="bgv_cleared", approved_salary=1300000, expected_salary=1500000
    )

    client.post(f"/applications/{application.id}/offer/generate", json={"start_date": "2026-09-01"})

    assert captured["approved_salary"] == "1300000.0"


def test_generate_offer_resolves_reporting_manager_from_job_when_no_override(client, db_session, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return FAKE_OFFER_RESULT

    monkeypatch.setattr("app.offers.router.generate_offer_letter", fake_generate)

    manager = _make_hiring_manager(db_session, full_name="John Smith")
    job = _make_job(db_session, hiring_manager_id=manager.id)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    client.post(f"/applications/{application.id}/offer/generate", json={"start_date": "2026-09-01"})

    assert captured["reporting_manager_name"] == "John Smith"


def test_generate_offer_override_reporting_manager_takes_precedence(client, db_session, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return FAKE_OFFER_RESULT

    monkeypatch.setattr("app.offers.router.generate_offer_letter", fake_generate)

    manager = _make_hiring_manager(db_session, full_name="John Smith")
    job = _make_job(db_session, hiring_manager_id=manager.id)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01", "reporting_manager_name": "Override Manager"},
    )

    assert captured["reporting_manager_name"] == "Override Manager"


def test_generate_offer_regenerate_updates_existing_offer(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.offers.router.generate_offer_letter",
        lambda **kwargs: FAKE_OFFER_RESULT,
    )

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)
    _make_offer(db_session, application, offer_letter_text="Old draft")

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    assert response.json()["offer_letter_text"] == FAKE_OFFER_RESULT["offer_letter_text"]

    offers = db_session.query(Offer).filter(Offer.application_id == application.id).all()
    assert len(offers) == 1


# --- /offer/mark-signed ------------------------------------------------------


def test_mark_offer_signed_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application)

    response = client.post(
        f"/applications/{application.id}/offer/mark-signed",
        json={"docusign_envelope_id": "env-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["signed"] is True
    assert body["docusign_envelope_id"] == "env-123"
    assert body["onboarding_status"] == "in_progress"

    db_session.refresh(application)
    assert application.status == "onboarding_started"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "offer_signed")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details["docusign_envelope_id"] == "env-123"


def test_mark_offer_signed_without_envelope_id(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application)

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["signed"] is True
    assert body["docusign_envelope_id"] is None


def test_mark_offer_signed_requires_offer_to_exist(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared")

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 404


def test_mark_offer_signed_application_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/offer/mark-signed", json={})
    assert response.status_code == 404


# --- /offer/complete-onboarding ----------------------------------------------


def test_complete_onboarding_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="onboarding_started")
    _make_offer(db_session, application, signed=True, onboarding_status="in_progress")

    response = client.post(f"/applications/{application.id}/offer/complete-onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_status"] == "completed"

    db_session.refresh(application)
    assert application.status == "onboarding_completed"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "onboarding_completed")
        .one_or_none()
    )
    assert audit_entry is not None


def test_complete_onboarding_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application)

    response = client.post(f"/applications/{application.id}/offer/complete-onboarding")

    assert response.status_code == 400


def test_complete_onboarding_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/offer/complete-onboarding")
    assert response.status_code == 404


# --- GET /offer -----------------------------------------------------------------


def test_get_offer_success(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    offer = _make_offer(db_session, application, offer_letter_text="Dear Jane Doe...")

    response = client.get(f"/applications/{application.id}/offer")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(offer.id)
    assert body["offer_letter_text"] == "Dear Jane Doe..."


def test_get_offer_not_found_when_none_generated(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="bgv_cleared")

    response = client.get(f"/applications/{application.id}/offer")

    assert response.status_code == 404


def test_get_offer_application_not_found(client):
    response = client.get(f"/applications/{uuid.uuid4()}/offer")
    assert response.status_code == 404


# --- DocuSign envelope creation on /offer/generate ---------------------------


def test_generate_offer_creates_real_docusign_envelope_when_sender_connected(client, db_session, monkeypatch):
    monkeypatch.setattr("app.offers.router.generate_offer_letter", lambda **kwargs: FAKE_OFFER_RESULT)

    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    captured = {}

    def fake_create_envelope(refresh_token, **kwargs):
        captured["refresh_token"] = refresh_token
        captured["kwargs"] = kwargs
        return "env-real-123"

    monkeypatch.setattr("app.offers.router.create_envelope", fake_create_envelope)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, full_name="Jane Doe", email="jane@example.com")
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["docusign_envelope_id"] == "env-real-123"

    offer = db_session.query(Offer).filter(Offer.application_id == application.id).one()
    assert offer.docusign_sender_id == admin.id

    # The stored refresh token was decrypted before being handed to the DocuSign client.
    assert captured["refresh_token"] == "refresh-token"
    assert captured["kwargs"]["signer_email"] == "jane@example.com"
    assert captured["kwargs"]["signer_name"] == "Jane Doe"
    assert captured["kwargs"]["document_text"] == FAKE_OFFER_RESULT["offer_letter_text"]


def test_generate_offer_without_docusign_connection_falls_back_manual(client, db_session, monkeypatch):
    # No DocuSign integration for the generating user -- existing manual flow untouched.
    monkeypatch.setattr("app.offers.router.generate_offer_letter", lambda **kwargs: FAKE_OFFER_RESULT)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="jane@example.com")
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    assert response.json()["docusign_envelope_id"] is None

    offer = db_session.query(Offer).filter(Offer.application_id == application.id).one()
    assert offer.docusign_sender_id is None


def test_generate_offer_without_candidate_email_skips_docusign(client, db_session, monkeypatch):
    # Sender is connected, but there's no address to send the envelope to.
    monkeypatch.setattr("app.offers.router.generate_offer_letter", lambda **kwargs: FAKE_OFFER_RESULT)
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    def fail_create_envelope(refresh_token, **kwargs):
        raise AssertionError("create_envelope should not be called without a candidate email")

    monkeypatch.setattr("app.offers.router.create_envelope", fail_create_envelope)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email=None)
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    assert response.json()["docusign_envelope_id"] is None


def test_generate_offer_docusign_failure_falls_back_gracefully(client, db_session, monkeypatch):
    monkeypatch.setattr("app.offers.router.generate_offer_letter", lambda **kwargs: FAKE_OFFER_RESULT)
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    def fake_create_envelope(refresh_token, **kwargs):
        raise DocuSignError("DocuSign API is down")

    monkeypatch.setattr("app.offers.router.create_envelope", fake_create_envelope)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session, email="jane@example.com")
    application = _make_application(db_session, job, candidate, status="bgv_cleared", approved_salary=1300000)

    response = client.post(
        f"/applications/{application.id}/offer/generate",
        json={"start_date": "2026-09-01"},
    )

    assert response.status_code == 200
    assert response.json()["docusign_envelope_id"] is None

    db_session.refresh(application)
    assert application.status == "offer_sent"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "docusign_envelope_creation_failed", AuditLog.entity_id == application.id)
        .one_or_none()
    )
    assert audit_entry is not None


# --- DocuSign status check on /offer/mark-signed -----------------------------


def test_mark_offer_signed_real_envelope_completed_marks_signed(client, db_session, monkeypatch):
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application, docusign_envelope_id="env-real-123", docusign_sender_id=admin.id)

    captured = {}

    def fake_get_envelope_status(refresh_token, envelope_id):
        captured["refresh_token"] = refresh_token
        captured["envelope_id"] = envelope_id
        return "completed"

    monkeypatch.setattr("app.offers.router.get_envelope_status", fake_get_envelope_status)

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["signed"] is True
    assert body["onboarding_status"] == "in_progress"

    db_session.refresh(application)
    assert application.status == "onboarding_started"

    assert captured["refresh_token"] == "refresh-token"
    assert captured["envelope_id"] == "env-real-123"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "offer_signed")
        .one_or_none()
    )
    assert audit_entry.details["docusign_status"] == "completed"


def test_mark_offer_signed_real_envelope_pending_returns_409(client, db_session, monkeypatch):
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    offer = _make_offer(db_session, application, docusign_envelope_id="env-real-123", docusign_sender_id=admin.id)

    monkeypatch.setattr("app.offers.router.get_envelope_status", lambda refresh_token, envelope_id: "sent")

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 409

    db_session.refresh(offer)
    assert offer.signed is False
    db_session.refresh(application)
    assert application.status == "offer_sent"


def test_mark_offer_signed_real_envelope_manual_override_ignored(client, db_session, monkeypatch):
    # A manually-supplied envelope ID must not bypass the real status check.
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application, docusign_envelope_id="env-real-123", docusign_sender_id=admin.id)

    monkeypatch.setattr("app.offers.router.get_envelope_status", lambda refresh_token, envelope_id: "sent")

    response = client.post(
        f"/applications/{application.id}/offer/mark-signed",
        json={"docusign_envelope_id": "some-other-id"},
    )

    assert response.status_code == 409


def test_mark_offer_signed_real_envelope_api_error_returns_502(client, db_session, monkeypatch):
    admin = _get_test_admin(db_session)
    _connect_docusign(db_session, admin)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application, docusign_envelope_id="env-real-123", docusign_sender_id=admin.id)

    def fake_get_envelope_status(refresh_token, envelope_id):
        raise DocuSignError("DocuSign API is down")

    monkeypatch.setattr("app.offers.router.get_envelope_status", fake_get_envelope_status)

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 502


def test_mark_offer_signed_real_envelope_disconnected_sender_returns_409(client, db_session):
    # The sender's DocuSign connection was set up at generate time, but no
    # UserIntegration row exists now (e.g. they disconnected) -- nothing to check against.
    admin = _get_test_admin(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="offer_sent")
    _make_offer(db_session, application, docusign_envelope_id="env-real-123", docusign_sender_id=admin.id)

    response = client.post(f"/applications/{application.id}/offer/mark-signed", json={})

    assert response.status_code == 409
