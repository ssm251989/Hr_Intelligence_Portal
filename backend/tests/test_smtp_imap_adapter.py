"""platform/connectors/providers/smtp.py + imap.py (Part 3 CHECKS). Fakes smtplib.SMTP /
imaplib.IMAP4_SSL directly -- this codebase's own established pattern (see
tests/test_hr_email.py's own docstring on why: no aiosmtpd/fake-IMAP-server dependency,
just fake the stdlib client classes the real adapter calls)."""

import email
import imaplib

import pytest

from app.platform.connectors.capabilities import OutboundEmail
from app.platform.connectors.providers.imap import ImapAdapter
from app.platform.connectors.providers.smtp import SmtpAdapter


class _FakeSmtpConnection:
    instances: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.tls_started = False
        self.logged_in = None
        self.sent: list = []
        _FakeSmtpConnection.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.tls_started = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message, to_addrs=None):
        self.sent.append((message, to_addrs))


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSmtpConnection.instances.clear()
    yield


def test_smtp_send_logs_in_and_sends_to_every_recipient(monkeypatch):
    import app.platform.connectors.providers.smtp as smtp_module

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", _FakeSmtpConnection)
    adapter = SmtpAdapter({"host": "smtp.example.com", "port": 587, "username": "hr@example.com", "use_tls": True}, {"password": "hunter2"})

    result = adapter.send(OutboundEmail(to=["candidate@example.com"], cc=["hr2@example.com"], subject="Hi", body_text="Body"))

    assert result.success is True
    conn = _FakeSmtpConnection.instances[0]
    assert conn.tls_started is True
    assert conn.logged_in == ("hr@example.com", "hunter2")
    message, recipients = conn.sent[0]
    assert set(recipients) == {"candidate@example.com", "hr2@example.com"}
    assert message["Subject"] == "Hi"


def test_smtp_send_failure_reports_error_not_an_exception(monkeypatch):
    import smtplib

    import app.platform.connectors.providers.smtp as smtp_module

    class _RefusingSmtp(_FakeSmtpConnection):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", _RefusingSmtp)
    adapter = SmtpAdapter({"host": "smtp.example.com", "port": 587, "username": "hr@example.com"}, {"password": "wrong"})

    result = adapter.send(OutboundEmail(to=["candidate@example.com"], subject="Hi", body_text="Body"))

    assert result.success is False
    assert result.error


def test_smtp_test_connection_reports_failure_without_raising(monkeypatch):
    import app.platform.connectors.providers.smtp as smtp_module

    class _UnreachableSmtp:
        def __init__(self, host, port, timeout=None):
            raise OSError("Connection refused")

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", _UnreachableSmtp)
    adapter = SmtpAdapter({"host": "nope.example.com", "port": 587, "username": "hr@example.com"}, {"password": "x"})

    result = adapter.test_connection()

    assert result.success is False
    assert "Connection refused" in (result.error or "")


class _FakeImapConnection:
    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.selected = None

    def login(self, username, password):
        if password != "correct":
            raise imaplib.IMAP4.error("authentication failed")

    def select(self, mailbox):
        self.selected = mailbox

    def search(self, charset, criteria):
        return "OK", [b"1"]

    def fetch(self, uid, what):
        raw = email.message_from_string(
            "From: candidate@example.com\r\nTo: hr@example.com\r\nSubject: Re: Interview\r\n"
            "Message-ID: <abc@example.com>\r\n\r\nI accept.\r\n"
        ).as_bytes()
        return "OK", [(b"1 (RFC822 {123}", raw)]

    def close(self):
        pass

    def logout(self):
        pass


def test_imap_poll_parses_messages_into_inbound_email(monkeypatch):
    import app.platform.connectors.providers.imap as imap_module

    monkeypatch.setattr(imap_module.imaplib, "IMAP4_SSL", _FakeImapConnection)
    adapter = ImapAdapter({"host": "imap.example.com", "port": 993, "username": "hr@example.com"}, {"password": "correct"})

    messages = adapter.poll(since=None)

    assert len(messages) == 1
    assert messages[0].from_address == "candidate@example.com"
    assert messages[0].subject == "Re: Interview"
    assert "I accept" in messages[0].body_text


def test_imap_test_connection_reports_auth_failure(monkeypatch):
    import app.platform.connectors.providers.imap as imap_module

    monkeypatch.setattr(imap_module.imaplib, "IMAP4_SSL", _FakeImapConnection)
    adapter = ImapAdapter({"host": "imap.example.com", "port": 993, "username": "hr@example.com"}, {"password": "wrong"})

    result = adapter.test_connection()

    assert result.success is False
