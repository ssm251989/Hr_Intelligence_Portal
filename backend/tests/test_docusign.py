from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.integrations.docusign import (
    DocuSignError,
    build_authorization_url,
    create_envelope,
    exchange_code_for_refresh_token,
    get_envelope_status,
)


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_build_authorization_url_uses_authorization_code_grant_no_pkce():
    # Standard Authorization Code Grant -- no code_challenge/code_verifier params at all,
    # unlike the Google flow.
    auth_url = build_authorization_url("state-123")

    parsed = urlparse(auth_url)
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["signature"]
    assert query["state"] == ["state-123"]
    assert "code_challenge" not in query
    assert "code_verifier" not in query


def test_exchange_code_for_refresh_token_success(monkeypatch):
    captured = {}

    def fake_post(url, data, auth, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        return _FakeResponse({"access_token": "at", "refresh_token": "rt-123"})

    monkeypatch.setattr(httpx, "post", fake_post)

    refresh_token = exchange_code_for_refresh_token("auth-code")

    assert refresh_token == "rt-123"
    assert captured["data"] == {"grant_type": "authorization_code", "code": "auth-code"}


def test_exchange_code_for_refresh_token_missing_refresh_token_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"access_token": "at"}))

    with pytest.raises(DocuSignError):
        exchange_code_for_refresh_token("auth-code")


def test_exchange_code_for_refresh_token_http_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=401))

    with pytest.raises(DocuSignError):
        exchange_code_for_refresh_token("bad-code")


def test_create_envelope_success(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/oauth/token"):
            return _FakeResponse({"access_token": "at-123", "refresh_token": "rt"})
        return _FakeResponse({"envelopeId": "env-abc"})

    monkeypatch.setattr(httpx, "post", fake_post)

    envelope_id = create_envelope(
        "refresh-token",
        document_text="Dear Jane, ...",
        document_name="Offer Letter - Jane Doe",
        signer_email="jane@example.com",
        signer_name="Jane Doe",
    )

    assert envelope_id == "env-abc"
    token_call, envelope_call = calls
    assert token_call[1]["data"] == {"grant_type": "refresh_token", "refresh_token": "refresh-token"}
    envelope_body = envelope_call[1]["json"]
    assert envelope_body["recipients"]["signers"][0]["email"] == "jane@example.com"
    assert envelope_call[1]["headers"] == {"Authorization": "Bearer at-123"}


def test_create_envelope_missing_envelope_id_raises(monkeypatch):
    def fake_post(url, **kwargs):
        if url.endswith("/oauth/token"):
            return _FakeResponse({"access_token": "at-123", "refresh_token": "rt"})
        return _FakeResponse({})

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(DocuSignError):
        create_envelope(
            "refresh-token",
            document_text="text",
            document_name="doc",
            signer_email="a@example.com",
            signer_name="A",
        )


def test_get_envelope_status_success(monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse({"access_token": "at-123", "refresh_token": "rt"})

    def fake_get(url, **kwargs):
        assert kwargs["headers"] == {"Authorization": "Bearer at-123"}
        return _FakeResponse({"status": "completed"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    status = get_envelope_status("refresh-token", "env-abc")

    assert status == "completed"


def test_get_envelope_status_http_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"access_token": "at-123"}))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse({}, status_code=500))

    with pytest.raises(DocuSignError):
        get_envelope_status("refresh-token", "env-abc")
