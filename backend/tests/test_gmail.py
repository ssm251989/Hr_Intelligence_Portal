import pytest

from app.integrations.gmail import GmailError, send_email


class _FakeMessages:
    def __init__(self, captured, fail=False):
        self._captured = captured
        self._fail = fail

    def send(self, userId, body):
        self._captured["userId"] = userId
        self._captured["body"] = body
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("Gmail API is down")
        return {"id": "msg_123"}


class _FakeUsers:
    def __init__(self, captured, fail=False):
        self._captured = captured
        self._fail = fail

    def messages(self):
        return _FakeMessages(self._captured, fail=self._fail)


class _FakeService:
    def __init__(self, captured, fail=False):
        self._captured = captured
        self._fail = fail

    def users(self):
        return _FakeUsers(self._captured, fail=self._fail)


def _patch_build(monkeypatch, fail=False):
    captured = {}
    monkeypatch.setattr("app.integrations.gmail.build", lambda *args, **kwargs: _FakeService(captured, fail=fail))
    return captured


def test_send_email_encodes_message_and_returns_message_id(monkeypatch):
    captured = _patch_build(monkeypatch)

    message_id = send_email(
        "fake-refresh-token", to="recruiter@example.com", subject="New application", body="Someone applied."
    )

    assert message_id == "msg_123"
    assert captured["userId"] == "me"
    assert "raw" in captured["body"]
    # base64url-encoded RFC 2822 message -- just confirm it decodes back to the headers/body
    # we sent rather than asserting on the raw base64 string itself.
    import base64

    decoded = base64.urlsafe_b64decode(captured["body"]["raw"]).decode("utf-8").lower()
    assert "to: recruiter@example.com" in decoded
    assert "subject: new application" in decoded
    assert "someone applied." in decoded


def test_send_email_wraps_api_failures_in_gmail_error(monkeypatch):
    _patch_build(monkeypatch, fail=True)

    with pytest.raises(GmailError):
        send_email("fake-refresh-token", to="recruiter@example.com", subject="Subject", body="Body")
