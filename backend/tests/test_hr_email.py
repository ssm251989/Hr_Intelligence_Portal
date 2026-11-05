"""app/integrations/hr_email.py's send_hr_email -- specifically its MIME-attachment support
(EmailAttachment), added so the pick-2-of-3 negotiation mechanic's confirmation step
(app/interview_scheduling/negotiation.py _finalize) can attach a generated .ics calendar
invite. Every other test in this codebase that exercises an HR email send mocks
send_hr_email itself; this file is the one place that exercises its own real MIME
construction, by faking smtplib.SMTP rather than send_hr_email."""

from app.core.crypto import encrypt
from app.integrations import hr_email
from app.integrations.hr_email import EmailAttachment, send_hr_email
from app.models.hr_integration import HrIntegration


class _FakeSmtpConnection:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message, to_addrs=None):
        _SENT.append((message, to_addrs))


_SENT: list = []


def _install_fake_smtp(monkeypatch) -> list:
    _SENT.clear()
    monkeypatch.setattr(hr_email.smtplib, "SMTP", _FakeSmtpConnection)
    return _SENT


def _hr_integration() -> HrIntegration:
    return HrIntegration(
        id=1, smtp_host="smtp.example.com", smtp_port=587, use_tls=True,
        smtp_username="hr@example.com", smtp_password=encrypt("hr-smtp-password"), from_address="hr@example.com",
    )


def test_send_hr_email_with_no_attachment_sends_a_plain_single_part_message(monkeypatch):
    sent = _install_fake_smtp(monkeypatch)
    send_hr_email(_hr_integration(), to="candidate@example.com", subject="Hello", body="plain body")

    assert len(sent) == 1
    message, to_addrs = sent[0]
    assert to_addrs == ["candidate@example.com"]
    assert list(message.iter_attachments()) == []
    assert message.get_content().strip() == "plain body"


def test_send_hr_email_attaches_the_ics_file_with_correct_mime_structure(monkeypatch):
    sent = _install_fake_smtp(monkeypatch)
    ics_bytes = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    attachment = EmailAttachment(filename="interview.ics", content=ics_bytes, maintype="text", subtype="calendar")

    send_hr_email(
        _hr_integration(), to="candidate@example.com", subject="Interview confirmed: Backend Engineer",
        body="A calendar invite is attached.", attachment=attachment,
    )

    assert len(sent) == 1
    message, _ = sent[0]
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    part = attachments[0]
    assert part.get_content_type() == "text/calendar"
    assert part.get_filename() == "interview.ics"
    assert part.get_content_disposition() == "attachment"
    assert part.get_payload(decode=True) == ics_bytes
    # The plain-text body must still be present alongside the attachment, not replaced by it.
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "A calendar invite is attached."


def test_send_hr_email_with_html_body_sends_multipart_alternative_with_both_parts(monkeypatch):
    sent = _install_fake_smtp(monkeypatch)
    html = "<html><body><h1>Hi</h1><p>Choose a slot.</p></body></html>"

    send_hr_email(
        _hr_integration(), to="candidate@example.com", subject="Interview scheduling for Backend Engineer",
        body="Plain-text fallback body.", html_body=html,
    )

    assert len(sent) == 1
    message, _ = sent[0]
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Plain-text fallback body."
    assert message.get_body(preferencelist=("html",)).get_content().strip() == html
    # Explicitly preferring plain must still resolve to the plain part, not the html one --
    # proves this is a real multipart/alternative, not html replacing the plain body.
    assert message.get_content_type() == "multipart/alternative"


def test_send_hr_email_html_body_and_attachment_together(monkeypatch):
    """The negotiation confirmation email (html_body) and the .ics attachment
    (EmailAttachment) are independent features that must compose -- a future combined
    send (a branded HTML confirmation with the .ics still attached) must not silently
    drop either part."""
    sent = _install_fake_smtp(monkeypatch)
    ics_bytes = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
    attachment = EmailAttachment(filename="interview.ics", content=ics_bytes, maintype="text", subtype="calendar")

    send_hr_email(
        _hr_integration(), to="candidate@example.com", subject="Interview confirmed",
        body="plain", html_body="<p>html</p>", attachment=attachment,
    )

    message, _ = sent[0]
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "plain"
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<p>html</p>"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == ics_bytes


def test_send_hr_email_attachment_bytes_survive_exactly_including_crlf(monkeypatch):
    """.ics is RFC 5545 -- its CRLF line endings must round-trip byte-for-byte, not get
    silently normalized to bare LF the way passing the content as `str` would (the text
    content manager rewrites line endings; the bytes handler used here does not)."""
    sent = _install_fake_smtp(monkeypatch)
    ics_bytes = b"BEGIN:VCALENDAR\r\nSUMMARY:Interview: Jane \xe2\x80\x94 Doe\r\nEND:VCALENDAR\r\n"
    attachment = EmailAttachment(filename="interview.ics", content=ics_bytes, maintype="text", subtype="calendar")

    send_hr_email(_hr_integration(), to="candidate@example.com", subject="Interview confirmed", body="body", attachment=attachment)

    message, _ = sent[0]
    part = list(message.iter_attachments())[0]
    assert part.get_payload(decode=True) == ics_bytes
