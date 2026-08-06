import base64
from urllib.parse import urlencode

import httpx

from app.core.config import settings

TOKEN_PATH = "/oauth/token"
AUTHORIZE_PATH = "/oauth/auth"
SCOPES = "signature"
# Envelope statuses that mean "everyone has signed" -- anything else (sent, delivered,
# declined, voided, ...) is not a completed signature yet.
COMPLETED_STATUS = "completed"


class DocuSignError(Exception):
    """Raised when talking to DocuSign's OAuth or eSignature APIs fails."""


def build_authorization_url(state: str) -> str:
    # Standard Authorization Code Grant (no PKCE) -- the DocuSign app is registered as a
    # confidential client, authenticating the token exchange with integration key + secret.
    params = {
        "response_type": "code",
        "scope": SCOPES,
        "client_id": settings.DOCUSIGN_INTEGRATION_KEY,
        "redirect_uri": settings.DOCUSIGN_REDIRECT_URI,
        "state": state,
    }
    return f"{settings.DOCUSIGN_AUTH_BASE_URL}{AUTHORIZE_PATH}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    try:
        response = httpx.post(
            f"{settings.DOCUSIGN_AUTH_BASE_URL}{TOKEN_PATH}",
            data=data,
            auth=(settings.DOCUSIGN_INTEGRATION_KEY, settings.DOCUSIGN_SECRET_KEY),
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocuSignError(f"DocuSign token request failed: {exc}") from exc
    return response.json()


def exchange_code_for_refresh_token(code: str) -> str:
    token_data = _token_request({"grant_type": "authorization_code", "code": code})
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise DocuSignError("DocuSign did not return a refresh token.")
    return refresh_token


def _get_access_token(refresh_token: str) -> str:
    token_data = _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
    access_token = token_data.get("access_token")
    if not access_token:
        raise DocuSignError("DocuSign did not return an access token.")
    return access_token


def create_envelope(
    refresh_token: str,
    *,
    document_text: str,
    document_name: str,
    signer_email: str,
    signer_name: str,
) -> str:
    access_token = _get_access_token(refresh_token)
    envelope_definition = {
        "emailSubject": f"Please sign: {document_name}",
        "documents": [
            {
                "documentBase64": base64.b64encode(document_text.encode("utf-8")).decode("utf-8"),
                "name": document_name,
                "fileExtension": "txt",
                "documentId": "1",
            }
        ],
        "recipients": {
            "signers": [
                {
                    "email": signer_email,
                    "name": signer_name,
                    "recipientId": "1",
                    "routingOrder": "1",
                    "tabs": {
                        "signHereTabs": [
                            {"documentId": "1", "pageNumber": "1", "xPosition": "100", "yPosition": "700"}
                        ]
                    },
                }
            ]
        },
        "status": "sent",
    }
    try:
        response = httpx.post(
            f"{settings.DOCUSIGN_API_BASE_URL}/restapi/v2.1/accounts/{settings.DOCUSIGN_ACCOUNT_ID}/envelopes",
            json=envelope_definition,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocuSignError(f"Failed to create DocuSign envelope: {exc}") from exc

    envelope_id = response.json().get("envelopeId")
    if not envelope_id:
        raise DocuSignError("DocuSign did not return an envelope ID.")
    return envelope_id


def get_envelope_status(refresh_token: str, envelope_id: str) -> str:
    access_token = _get_access_token(refresh_token)
    try:
        response = httpx.get(
            f"{settings.DOCUSIGN_API_BASE_URL}/restapi/v2.1/accounts/{settings.DOCUSIGN_ACCOUNT_ID}/envelopes/{envelope_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocuSignError(f"Failed to check envelope status: {exc}") from exc

    status = response.json().get("status")
    if not status:
        raise DocuSignError("DocuSign did not return an envelope status.")
    return status
