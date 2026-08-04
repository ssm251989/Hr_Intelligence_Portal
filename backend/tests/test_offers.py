import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.user import User

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


def _make_candidate(db_session, full_name="Jane Doe") -> Candidate:
    candidate = Candidate(full_name=full_name)
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


def _make_offer(db_session, application, offer_letter_text="Existing letter", signed=False, onboarding_status="not_started"):
    offer = Offer(
        application_id=application.id,
        offer_letter_text=offer_letter_text,
        signed=signed,
        onboarding_status=onboarding_status,
    )
    db_session.add(offer)
    db_session.commit()
    db_session.refresh(offer)
    return offer


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
