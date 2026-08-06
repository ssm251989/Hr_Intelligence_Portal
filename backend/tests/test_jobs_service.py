import uuid

from app.core.crypto import encrypt
from app.integrations.gmail import GmailError
from app.jobs.service import notify_job_owner_of_new_application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.models.user_integration import UserIntegration


def _make_user(db_session, email="recruiter@example.com") -> User:
    user = User(email=email, hashed_password="not-a-real-hash", full_name="Recruiter", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
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


def _connect_google(db_session, user, refresh_token="refresh-token") -> UserIntegration:
    integration = UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt(refresh_token))
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def test_sends_email_when_enabled_and_connected(db_session, monkeypatch):
    owner = _make_user(db_session)
    _connect_google(db_session, owner)
    job = _make_job(
        db_session, created_by=owner.id, publish_settings={"email_notifications": True},
    )
    candidate = _make_candidate(db_session, full_name="Jordan Applicant")

    captured = {}

    def fake_send_email(refresh_token, *, to, subject, body):
        captured.update(refresh_token=refresh_token, to=to, subject=subject, body=body)
        return "msg_1"

    monkeypatch.setattr("app.jobs.service.send_email", fake_send_email)

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert captured["to"] == owner.email
    assert job.title in captured["subject"]
    assert "Jordan Applicant" in captured["body"]

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "new_application_email_sent")
        .one_or_none()
    )
    assert entry is not None
    assert entry.details["to"] == owner.email


def test_does_not_send_when_notifications_disabled(db_session, monkeypatch):
    owner = _make_user(db_session)
    _connect_google(db_session, owner)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": False})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []


def test_does_not_send_when_owner_not_connected(db_session, monkeypatch):
    owner = _make_user(db_session)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []


def test_does_not_send_when_job_has_no_owner(db_session, monkeypatch):
    job = _make_job(db_session, created_by=None, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []


def test_gmail_failure_is_caught_and_logged_not_raised(db_session, monkeypatch):
    owner = _make_user(db_session)
    _connect_google(db_session, owner)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    def fake_send_email(*args, **kwargs):
        raise GmailError("insufficient scope -- reconnect required")

    monkeypatch.setattr("app.jobs.service.send_email", fake_send_email)

    notify_job_owner_of_new_application(db_session, job, candidate)  # must not raise

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "new_application_email_failed")
        .one_or_none()
    )
    assert entry is not None
    assert "insufficient scope" in entry.details["error"]


def test_undecryptable_refresh_token_is_caught_and_logged_not_raised(db_session, monkeypatch):
    owner = _make_user(db_session)
    integration = UserIntegration(user_id=owner.id, provider="google", refresh_token="not-a-valid-fernet-token")
    db_session.add(integration)
    db_session.commit()
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    notify_job_owner_of_new_application(db_session, job, candidate)  # must not raise

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "new_application_email_failed")
        .one_or_none()
    )
    assert entry is not None
