import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session) -> JobRole:
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, name="Jane Doe") -> Candidate:
    candidate = Candidate(full_name=name)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="received", match_score=None) -> Application:
    application = Application(
        job_role_id=job.id, candidate_id=candidate.id, status=status, match_score=match_score
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def test_shortlist_queue_sorted_by_match_score(client, db_session):
    job = _make_job(db_session)
    other_job = _make_job(db_session)

    low_scorer = _make_application(db_session, job, _make_candidate(db_session, "Low"), status="screened", match_score=60)
    high_scorer = _make_application(db_session, job, _make_candidate(db_session, "High"), status="screened", match_score=90)
    _make_application(db_session, job, _make_candidate(db_session, "Unscreened"), status="received")
    _make_application(db_session, other_job, _make_candidate(db_session, "OtherJob"), status="screened", match_score=99)

    response = client.get(f"/jobs/{job.id}/shortlist")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(high_scorer.id), str(low_scorer.id)]


def test_shortlist_decision_select(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=75)

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "select", "notes": "Strong fit", "decided_by": "hr_jane"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "hr_shortlisting_decision")
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.actor == "hr_jane"
    assert audit_entry.details["decision"] == "select"
    assert audit_entry.details["notes"] == "Strong fit"


def test_shortlist_decision_reject(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=40)

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "hr_rejected"


def test_shortlist_decision_defaults_actor_to_current_user_email(client, db_session, make_auth_headers):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", match_score=75)

    headers = make_auth_headers(role="recruiter", email="recruiter@example.com")
    client.post(f"/applications/{application.id}/shortlist-decision", json={"decision": "select"}, headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "hr_shortlisting_decision")
        .one_or_none()
    )
    assert audit_entry.actor == "recruiter@example.com"


def test_shortlist_decision_requires_screened_status(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="received")

    response = client.post(
        f"/applications/{application.id}/shortlist-decision",
        json={"decision": "select"},
    )

    assert response.status_code == 400


def test_shortlist_decision_not_found(client):
    response = client.post(
        f"/applications/{uuid.uuid4()}/shortlist-decision",
        json={"decision": "select"},
    )
    assert response.status_code == 404
