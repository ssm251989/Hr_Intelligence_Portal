import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session, salary_band_min=800000, salary_band_max=1200000) -> JobRole:
    job = JobRole(title="Backend Engineer", salary_band_min=salary_band_min, salary_band_max=salary_band_max)
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


def _make_application(db_session, job, candidate, status="hr_selected", expected_salary=None) -> Application:
    application = Application(
        job_role_id=job.id, candidate_id=candidate.id, status=status, expected_salary=expected_salary
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def test_validate_salary_within_band(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected", expected_salary=1000000)

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 200
    assert response.json()["status"] == "salary_ok"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_validated")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details["within_band"] is True
    assert audit_entry.details["expected_salary"] == 1000000.0


def test_validate_salary_above_band(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="interview_selected", expected_salary=1500000)

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 200
    assert response.json()["status"] == "salary_above_band"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_validated")
        .one_or_none()
    )
    assert audit_entry.details["within_band"] is False


def test_validate_salary_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", expected_salary=1000000)

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 400


def test_validate_salary_missing_expected_salary_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected", expected_salary=None)

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 400


def test_validate_salary_missing_job_band_returns_400(client, db_session):
    job = _make_job(db_session, salary_band_min=None, salary_band_max=None)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected", expected_salary=1000000)

    response = client.post(f"/applications/{application.id}/validate-salary")

    assert response.status_code == 400


def test_validate_salary_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/validate-salary")
    assert response.status_code == 404


def test_approve_salary_approve_with_override(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="salary_above_band", expected_salary=1500000
    )

    response = client.post(
        f"/applications/{application.id}/approve-salary",
        json={"decision": "approve", "approved_salary": 1300000, "approved_by": "hr_jane"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "salary_approved"
    # expected_salary is what the candidate originally provided and must be untouched.
    assert body["expected_salary"] == 1500000.0
    # approved_salary holds the resolved (overridden) figure, in its own column.
    assert body["approved_salary"] == 1300000.0
    assert body["expected_salary"] != body["approved_salary"]

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_approval_decision")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.actor == "hr_jane"
    assert audit_entry.details["approved_salary"] == 1300000.0


def test_approve_salary_approve_without_override_uses_expected_salary(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="salary_above_band", expected_salary=1500000
    )

    response = client.post(f"/applications/{application.id}/approve-salary", json={"decision": "approve"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "salary_approved"
    assert body["expected_salary"] == 1500000.0
    # No override given, so approved_salary resolves to the existing expected_salary value.
    assert body["approved_salary"] == 1500000.0

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_approval_decision")
        .one_or_none()
    )
    assert audit_entry.details["approved_salary"] == 1500000.0


def test_approve_salary_reject(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="salary_above_band", expected_salary=1500000
    )

    response = client.post(f"/applications/{application.id}/approve-salary", json={"decision": "reject"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "salary_rejected"
    assert body["expected_salary"] == 1500000.0
    assert body["approved_salary"] is None

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_approval_decision")
        .one_or_none()
    )
    assert audit_entry.details["approved_salary"] is None


def test_approve_salary_wrong_status_returns_400(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="salary_ok", expected_salary=1000000)

    response = client.post(f"/applications/{application.id}/approve-salary", json={"decision": "approve"})

    assert response.status_code == 400


def test_approve_salary_defaults_actor_to_current_user_email(client, db_session, make_auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="salary_above_band", expected_salary=1500000
    )

    headers = make_auth_headers(role="hiring_manager", email="hiring-manager@example.com")
    client.post(f"/applications/{application.id}/approve-salary", json={"decision": "approve"}, headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "salary_approval_decision")
        .one_or_none()
    )
    assert audit_entry.actor == "hiring-manager@example.com"


def test_approve_salary_not_found(client):
    response = client.post(f"/applications/{uuid.uuid4()}/approve-salary", json={"decision": "approve"})
    assert response.status_code == 404


def test_get_salary_status_success(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="salary_ok", expected_salary=1000000)

    response = client.get(f"/applications/{application.id}/salary-status")

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == str(application.id)
    assert body["status"] == "salary_ok"
    assert body["expected_salary"] == 1000000.0
    assert body["approved_salary"] is None
    assert body["salary_band_min"] == 800000.0
    assert body["salary_band_max"] == 1200000.0


def test_get_salary_status_after_approval_shows_both_values(client, db_session):
    job = _make_job(db_session, 800000, 1200000)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="salary_above_band", expected_salary=1500000
    )
    client.post(
        f"/applications/{application.id}/approve-salary",
        json={"decision": "approve", "approved_salary": 1300000},
    )

    response = client.get(f"/applications/{application.id}/salary-status")

    assert response.status_code == 200
    body = response.json()
    assert body["expected_salary"] == 1500000.0
    assert body["approved_salary"] == 1300000.0
    assert body["expected_salary"] != body["approved_salary"]


def test_get_salary_status_not_found(client):
    response = client.get(f"/applications/{uuid.uuid4()}/salary-status")
    assert response.status_code == 404
