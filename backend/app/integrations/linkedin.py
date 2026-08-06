from urllib.parse import urlencode

import httpx

from app.core.config import settings

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
# "Sign In with LinkedIn using OpenID Connect" (openid + profile) plus "Share on
# LinkedIn" (w_member_social) -- both self-serve products, no partner approval needed.
SCOPES = "openid profile w_member_social"


class LinkedInError(Exception):
    """Raised when talking to LinkedIn's OAuth or Posts API fails."""


class LinkedInTokenExpiredError(LinkedInError):
    """Raised specifically when LinkedIn rejects the access token as expired/invalid.

    Standard/self-serve LinkedIn apps get a short-lived (~60 day) access token with no
    refresh token -- there's no way to silently renew it. Callers should treat this the
    same as "not connected" (fall back, never block the caller) and the user must
    reconnect via Settings.
    """


def build_authorization_url(state: str) -> str:
    # Standard Authorization Code Grant (no PKCE) -- same shape as the DocuSign flow.
    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def exchange_code_for_access_token(code: str) -> dict:
    """Returns {"access_token": str, "expires_in": int | None} (seconds until expiry)."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LinkedInError(f"LinkedIn token exchange failed: {exc}") from exc

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise LinkedInError("LinkedIn did not return an access token.")
    return {"access_token": access_token, "expires_in": data.get("expires_in")}


def get_member_urn(access_token: str) -> str:
    """Fetches the member's id via /v2/userinfo and returns it as a person URN."""
    try:
        response = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LinkedInError(f"Failed to fetch LinkedIn member info: {exc}") from exc

    sub = response.json().get("sub")
    if not sub:
        raise LinkedInError("LinkedIn did not return a member id (sub claim).")
    return f"urn:li:person:{sub}"


def create_hiring_announcement_post(access_token: str, *, member_urn: str, commentary: str) -> str:
    """Creates a PUBLIC text post authored by member_urn. Returns the created post's URN.

    Uses the current Posts API (POST /rest/posts), which replaced the older /v2/ugcPosts
    endpoint. A plain URL inside `commentary` is auto-unfurled into a link preview card by
    LinkedIn itself, so no image/thumbnail upload (Images API) is needed for a simple
    hiring announcement.
    """
    try:
        response = httpx.post(
            POSTS_URL,
            json={
                "author": member_urn,
                "commentary": commentary,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Linkedin-Version": settings.LINKEDIN_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise LinkedInError(f"Failed to create LinkedIn post: {exc}") from exc

    if response.status_code == 401:
        raise LinkedInTokenExpiredError("LinkedIn rejected the access token (expired or revoked).")
    if response.status_code >= 400:
        raise LinkedInError(f"LinkedIn post creation failed with status {response.status_code}: {response.text}")

    post_urn = response.headers.get("x-restli-id")
    if not post_urn:
        raise LinkedInError("LinkedIn did not return a post URN (x-restli-id header missing).")
    return post_urn
