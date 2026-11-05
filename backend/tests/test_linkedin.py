from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.integrations.linkedin import (
    LinkedInError,
    LinkedInTokenExpiredError,
    build_authorization_url,
    create_hiring_announcement_post,
    exchange_code_for_access_token,
    get_member_urn,
)


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, headers=None, text=""):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_build_authorization_url_uses_authorization_code_grant_with_expected_scopes():
    # Standard Authorization Code Grant, no PKCE -- same shape as the DocuSign flow.
    auth_url = build_authorization_url("state-123")

    parsed = urlparse(auth_url)
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile w_member_social"]
    assert query["state"] == ["state-123"]
    assert "code_challenge" not in query
    assert "code_verifier" not in query


def test_exchange_code_for_access_token_success(monkeypatch):
    captured = {}

    def fake_post(url, data, headers, timeout):
        captured["url"] = url
        captured["data"] = data
        return _FakeResponse({"access_token": "at-123", "expires_in": 5184000})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = exchange_code_for_access_token("auth-code")

    assert result == {"access_token": "at-123", "expires_in": 5184000}
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "auth-code"


def test_exchange_code_for_access_token_missing_token_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"expires_in": 100}))

    with pytest.raises(LinkedInError):
        exchange_code_for_access_token("auth-code")


def test_exchange_code_for_access_token_http_error_raises(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(LinkedInError):
        exchange_code_for_access_token("auth-code")


def test_get_member_urn_success(monkeypatch):
    def fake_get(url, headers, timeout):
        assert headers == {"Authorization": "Bearer at-123"}
        return _FakeResponse({"sub": "abc123"})

    monkeypatch.setattr(httpx, "get", fake_get)

    urn = get_member_urn("at-123")

    assert urn == "urn:li:person:abc123"


def test_get_member_urn_missing_sub_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse({}))

    with pytest.raises(LinkedInError):
        get_member_urn("at-123")


def test_create_hiring_announcement_post_success(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(status_code=201, headers={"x-restli-id": "urn:li:share:12345"})

    monkeypatch.setattr(httpx, "post", fake_post)

    post_urn = create_hiring_announcement_post(
        "at-123", member_urn="urn:li:person:abc123", commentary="We're hiring!"
    )

    assert post_urn == "urn:li:share:12345"
    assert captured["json"]["author"] == "urn:li:person:abc123"
    assert captured["json"]["visibility"] == "PUBLIC"
    assert captured["json"]["lifecycleState"] == "PUBLISHED"
    assert captured["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert "Linkedin-Version" in captured["headers"]


def test_create_hiring_announcement_post_401_raises_token_expired_error(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status_code=401, text="invalid token"))

    with pytest.raises(LinkedInTokenExpiredError):
        create_hiring_announcement_post("at-123", member_urn="urn:li:person:abc123", commentary="x")


def test_create_hiring_announcement_post_other_error_raises_generic_error(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status_code=422, text="bad request"))

    with pytest.raises(LinkedInError) as exc_info:
        create_hiring_announcement_post("at-123", member_urn="urn:li:person:abc123", commentary="x")
    assert not isinstance(exc_info.value, LinkedInTokenExpiredError)


def test_create_hiring_announcement_post_missing_urn_header_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status_code=201, headers={}))

    with pytest.raises(LinkedInError):
        create_hiring_announcement_post("at-123", member_urn="urn:li:person:abc123", commentary="x")


def test_create_hiring_announcement_post_network_error_raises(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(LinkedInError):
        create_hiring_announcement_post("at-123", member_urn="urn:li:person:abc123", commentary="x")
