import uuid

from app.core.crypto import encrypt
from app.integrations.hr_email import SmtpError
from app.jobs.service import notify_job_owner_of_new_application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.hr_integration import HrIntegration
from app.models.job_role import JobRole
from app.models.user import User


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


def _connect_hr_smtp(db_session, password="hr-smtp-password") -> HrIntegration:
    row = db_session.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db_session.add(row)
    row.smtp_host = "smtp.example.com"
    row.smtp_port = 587
    row.use_tls = True
    row.smtp_username = "hr@example.com"
    row.smtp_password = encrypt(password)
    row.from_address = "hr@example.com"
    db_session.commit()
    db_session.refresh(row)
    return row


def _disconnect_hr_smtp(db_session) -> None:
    # The hr_integrations row is a singleton (id=1) that -- like every other settings
    # singleton in this app -- an earlier test's own db.commit() can leave configured;
    # explicitly reset it rather than assuming isolation, same pattern
    # test_interview_scheduling.py's own settings tests already use.
    row = db_session.get(HrIntegration, 1)
    if row is not None:
        row.smtp_host = None
        row.smtp_username = None
        row.smtp_password = None
        db_session.commit()


def test_sends_email_via_hr_mailbox_when_enabled_and_configured(db_session, monkeypatch):
    # The job owner has NO personal Google connection at all -- sending must still work,
    # since it now sources credentials from the shared HR mailbox, not the owner's own.
    owner = _make_user(db_session)
    _connect_hr_smtp(db_session)
    job = _make_job(
        db_session, created_by=owner.id, publish_settings={"email_notifications": True},
    )
    candidate = _make_candidate(db_session, full_name="Jordan Applicant")

    captured = {}

    def fake_send_hr_email(hr_integration, *, to, subject, body):
        captured.update(to=to, subject=subject, body=body)

    monkeypatch.setattr("app.jobs.service.send_hr_email", fake_send_hr_email)

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
    _connect_hr_smtp(db_session)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": False})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_hr_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []


def test_does_not_send_when_hr_mailbox_not_configured(db_session, monkeypatch):
    # Replaces the old "owner not connected" case -- the owner's own connection no longer
    # matters at all; only the shared HR mailbox's SMTP configuration gates sending.
    _disconnect_hr_smtp(db_session)
    owner = _make_user(db_session)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_hr_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "new_application_email_skipped")
        .one_or_none()
    )
    assert entry is not None
    assert "SMTP" in entry.details["reason"]


def test_does_not_send_when_job_has_no_owner(db_session, monkeypatch):
    _connect_hr_smtp(db_session)
    job = _make_job(db_session, created_by=None, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    called = []
    monkeypatch.setattr("app.jobs.service.send_hr_email", lambda *a, **k: called.append(1))

    notify_job_owner_of_new_application(db_session, job, candidate)

    assert called == []


def test_smtp_failure_is_caught_and_logged_not_raised(db_session, monkeypatch):
    owner = _make_user(db_session)
    _connect_hr_smtp(db_session)
    job = _make_job(db_session, created_by=owner.id, publish_settings={"email_notifications": True})
    candidate = _make_candidate(db_session)

    def fake_send_hr_email(*args, **kwargs):
        raise SmtpError("Connection refused")

    monkeypatch.setattr("app.jobs.service.send_hr_email", fake_send_hr_email)

    notify_job_owner_of_new_application(db_session, job, candidate)  # must not raise

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == job.id, AuditLog.action == "new_application_email_failed")
        .one_or_none()
    )
    assert entry is not None
    assert "Connection refused" in entry.details["error"]


def test_undecryptable_hr_smtp_password_is_caught_and_logged_not_raised(db_session):
    owner = _make_user(db_session)
    row = db_session.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db_session.add(row)
    row.smtp_host = "smtp.example.com"
    row.smtp_username = "hr@example.com"
    row.smtp_password = "not-a-valid-fernet-token"
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
    assert "could not be decrypted" in entry.details["error"]
