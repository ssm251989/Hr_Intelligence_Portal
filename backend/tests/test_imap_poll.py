"""The shared HR mailbox's incoming side (app/integrations/imap_poll.py) -- dedup across
repeated polls, matching a known candidate's email, graceful handling of an unmatched
sender, and the poll job actually running on the existing 30-minute scheduler
(app/local_import/scheduler.py, shared with Part G's local-folder import scan rather than
a second scheduler)."""

from app.core.crypto import encrypt
from app.integrations import imap_poll
from app.local_import import scheduler as local_import_scheduler
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.hr_integration import HrIntegration


def _connect_hr_smtp_and_imap(db_session) -> HrIntegration:
    row = db_session.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db_session.add(row)
    row.smtp_host = "smtp.example.com"
    row.smtp_port = 587
    row.use_tls = True
    row.smtp_username = "hr@example.com"
    row.smtp_password = encrypt("hr-smtp-password")
    row.from_address = "hr@example.com"
    row.imap_host = "imap.example.com"
    row.imap_port = 993
    row.use_ssl = True
    row.imap_last_uid = None
    db_session.commit()
    db_session.refresh(row)
    return row


def _raw_message(*, from_address, message_id, subject="Re: application", to_address="hr@example.com") -> bytes:
    return (
        f"From: {from_address}\r\n"
        f"To: {to_address}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {message_id}\r\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "Hello, following up on my application.\r\n"
    ).encode("utf-8")


class FakeImapConnection:
    """Stands in for imaplib.IMAP4/IMAP4_SSL -- ignores the search criteria and always
    hands back every message it was constructed with, so a test can drive
    poll_hr_inbox's own message_id dedup path (the second line of defense against
    reprocessing, independent of the imap_last_uid checkpoint) by simply calling
    poll_hr_inbox twice against the same fake mailbox."""

    def __init__(self, messages: dict):
        self.messages = messages  # uid (int) -> raw bytes
        self.logged_out = False

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def uid(self, command, arg, *args):
        if command == "search":
            uids = sorted(self.messages.keys())
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "fetch":
            uid = int(arg)
            raw = self.messages.get(uid)
            if raw is None:
                return "NO", None
            return "OK", [(b"1 (RFC822 {%d}" % len(raw), raw)]
        return "NO", None

    def logout(self):
        self.logged_out = True


def _patch_connect(monkeypatch, connection: FakeImapConnection) -> None:
    monkeypatch.setattr(imap_poll, "_connect", lambda hr_integration: connection)


def test_poll_dedups_across_repeated_polls(db_session, monkeypatch):
    hr_integration = _connect_hr_smtp_and_imap(db_session)
    raw = _raw_message(from_address="unmatched-sender@example.com", message_id="<msg-1@example.com>")
    connection = FakeImapConnection({1: raw})
    _patch_connect(monkeypatch, connection)

    first = imap_poll.poll_hr_inbox(db_session, hr_integration)
    assert first == {"fetched": 1, "stored": 1, "matched": 0}

    # Same fake mailbox, same UID, same Message-ID -- simulates a poll that re-sees a UID
    # it already processed (e.g. after a crash before imap_last_uid advanced). The
    # message_id uniqueness check must catch it even though the checkpoint-based search
    # criteria alone can't be exercised by this fake connection.
    second = imap_poll.poll_hr_inbox(db_session, hr_integration)
    assert second == {"fetched": 1, "stored": 0, "matched": 0}

    rows = db_session.query(HrInboundEmail).filter(HrInboundEmail.message_id == "<msg-1@example.com>").all()
    assert len(rows) == 1


def test_poll_matches_a_known_candidates_email(db_session, monkeypatch):
    hr_integration = _connect_hr_smtp_and_imap(db_session)
    candidate = Candidate(full_name="Jane Doe", email="jane.doe@example.com")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    raw = _raw_message(from_address="Jane.Doe@Example.com", message_id="<msg-matched@example.com>")
    _patch_connect(monkeypatch, FakeImapConnection({1: raw}))

    result = imap_poll.poll_hr_inbox(db_session, hr_integration)

    assert result == {"fetched": 1, "stored": 1, "matched": 1}

    row = db_session.query(HrInboundEmail).filter(HrInboundEmail.message_id == "<msg-matched@example.com>").one()
    assert row.matched_candidate_id == candidate.id
    assert row.from_address == "jane.doe@example.com"

    timeline_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "candidate", AuditLog.entity_id == candidate.id, AuditLog.action == "inbound_email_received")
        .one_or_none()
    )
    assert timeline_entry is not None
    assert timeline_entry.details["hr_inbound_email_id"] == str(row.id)


def test_poll_handles_an_unmatched_sender_gracefully(db_session, monkeypatch):
    hr_integration = _connect_hr_smtp_and_imap(db_session)
    raw = _raw_message(from_address="stranger@example.com", message_id="<msg-unmatched@example.com>")
    _patch_connect(monkeypatch, FakeImapConnection({1: raw}))

    result = imap_poll.poll_hr_inbox(db_session, hr_integration)

    assert result == {"fetched": 1, "stored": 1, "matched": 0}

    row = db_session.query(HrInboundEmail).filter(HrInboundEmail.message_id == "<msg-unmatched@example.com>").one()
    assert row.matched_candidate_id is None
    assert row.matched_application_id is None

    assert (
        db_session.query(AuditLog).filter(AuditLog.action == "inbound_email_received", AuditLog.actor == "stranger@example.com").first()
        is None
    )


def test_poll_advances_the_uid_checkpoint(db_session, monkeypatch):
    hr_integration = _connect_hr_smtp_and_imap(db_session)
    raw = _raw_message(from_address="stranger@example.com", message_id="<msg-checkpoint@example.com>")
    _patch_connect(monkeypatch, FakeImapConnection({7: raw}))

    imap_poll.poll_hr_inbox(db_session, hr_integration)

    db_session.refresh(hr_integration)
    assert hr_integration.imap_last_uid == 7


# --- the poll job actually runs on the existing 30-minute scheduler (see
# app/local_import/scheduler.py -- the same BackgroundScheduler as Part G's local-folder
# import scan, not a second scheduler of its own) ---


def test_hr_inbox_poll_job_is_registered_on_the_shared_scheduler_at_a_fixed_30_minutes(client):
    # `client`'s TestClient runs this app's real lifespan (see app/main.py), so a real
    # BackgroundScheduler is already running with both jobs registered.
    job = local_import_scheduler._scheduler.get_job(local_import_scheduler.HR_INBOX_POLL_JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == 30 * 60


class _NonClosingSessionProxy:
    """SessionLocal() inside the scheduler module opens a session it closes itself when
    the job tick finishes -- wrap this test's own db_session so that close() is a no-op,
    letting the test keep querying/asserting against it afterward, same session, same
    (rolled-back-at-teardown) transaction."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def test_scheduled_hr_inbox_poll_runs_the_real_poll_when_configured(db_session, monkeypatch):
    _connect_hr_smtp_and_imap(db_session)
    raw = _raw_message(from_address="stranger@example.com", message_id="<msg-scheduled@example.com>")

    monkeypatch.setattr(imap_poll, "_connect", lambda hr_integration: FakeImapConnection({1: raw}))
    monkeypatch.setattr(local_import_scheduler, "SessionLocal", lambda: _NonClosingSessionProxy(db_session))

    local_import_scheduler._run_scheduled_hr_inbox_poll()

    row = db_session.query(HrInboundEmail).filter(HrInboundEmail.message_id == "<msg-scheduled@example.com>").one_or_none()
    assert row is not None


def test_scheduled_hr_inbox_poll_is_a_noop_when_imap_not_configured(db_session, monkeypatch):
    row = db_session.get(HrIntegration, 1)
    if row is not None:
        row.imap_host = None
        row.smtp_host = None
        row.smtp_username = None
        row.smtp_password = None
        db_session.commit()

    monkeypatch.setattr(local_import_scheduler, "SessionLocal", lambda: _NonClosingSessionProxy(db_session))

    local_import_scheduler._run_scheduled_hr_inbox_poll()  # must not raise, must not connect


def test_scheduled_hr_inbox_poll_catches_imap_error_without_crashing(db_session, monkeypatch):
    _connect_hr_smtp_and_imap(db_session)
    monkeypatch.setattr(local_import_scheduler, "SessionLocal", lambda: _NonClosingSessionProxy(db_session))
    monkeypatch.setattr(
        imap_poll, "_connect",
        lambda hr_integration: (_ for _ in ()).throw(imap_poll.ImapError("mailbox unreachable")),
    )

    local_import_scheduler._run_scheduled_hr_inbox_poll()  # must not raise
