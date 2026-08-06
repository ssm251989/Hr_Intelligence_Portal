import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from jose import JWTError
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.crypto import encrypt
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token
from app.integrations.docusign import DocuSignError
from app.integrations.docusign import build_authorization_url as build_docusign_authorization_url
from app.integrations.docusign import exchange_code_for_refresh_token as exchange_docusign_code_for_refresh_token
from app.integrations.google_calendar import (
    GoogleCalendarError,
    build_authorization_url,
    exchange_code_for_refresh_token,
    generate_code_verifier,
)
from app.integrations.linkedin import LinkedInError
from app.integrations.linkedin import build_authorization_url as build_linkedin_authorization_url
from app.integrations.linkedin import exchange_code_for_access_token as exchange_linkedin_code_for_access_token
from app.integrations.linkedin import get_member_urn
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.schemas.integration import DocuSignAuthUrl, GoogleAuthUrl, IntegrationStatus, LinkedInAuthUrl

router = APIRouter(tags=["integrations"])


def _get_integration(db: Session, user_id: uuid.UUID, provider: str) -> UserIntegration | None:
    return (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == user_id, UserIntegration.provider == provider)
        .first()
    )


@router.get("/integrations/google/connect", response_model=GoogleAuthUrl)
def connect_google(current_user: User = Depends(get_current_user)):
    # Returned as JSON rather than an HTTP redirect so the frontend can call this as a
    # normal authenticated fetch (Bearer header) and then navigate the browser itself --
    # a plain browser navigation to this endpoint couldn't carry the Authorization header.
    # The OAuth callback is a plain browser redirect with no Authorization header, so the
    # requesting user's id rides along in `state` as a short-lived JWT. The PKCE
    # code_verifier rides along too -- /connect and /callback are separate requests, so a
    # verifier held only in a local variable/Flow object wouldn't survive the round trip.
    code_verifier = generate_code_verifier()
    state = create_access_token(subject=str(current_user.id), extra_claims={"code_verifier": code_verifier})
    return GoogleAuthUrl(auth_url=build_authorization_url(state, code_verifier))


@router.get("/auth/google/callback", response_class=HTMLResponse)
def google_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(state)
        user_id = uuid.UUID(payload["sub"])
        code_verifier = payload["code_verifier"]
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        refresh_token = exchange_code_for_refresh_token(code, code_verifier)
    except GoogleCalendarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    integration = _get_integration(db, user.id, "google")
    if integration:
        integration.refresh_token = encrypt(refresh_token)
    else:
        integration = UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt(refresh_token))
        db.add(integration)
    db.commit()

    log_action(db, "user_integration", user.id, "google_calendar_connected", user.email, {"provider": "google"})

    return "<html><body>Google Calendar connected. You can close this tab and return to the app.</body></html>"


@router.get("/integrations/google/status", response_model=IntegrationStatus)
def google_status(
    user_id: uuid.UUID | None = Query(None, description="Check another user's status; defaults to the caller"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Connection status carries no secret material, so any authenticated user can look up
    # anyone else's -- e.g. a recruiter checking whether an interviewer has connected.
    integration = _get_integration(db, user_id or current_user.id, "google")
    return IntegrationStatus(
        connected=integration is not None,
        connected_at=integration.connected_at if integration else None,
    )


@router.get("/integrations/docusign/connect", response_model=DocuSignAuthUrl)
def connect_docusign(current_user: User = Depends(get_current_user)):
    # Same JSON-not-redirect reasoning as Google's /connect. This is a standard
    # Authorization Code Grant (no PKCE) -- the DocuSign app is configured as a
    # confidential client, so there's no code_verifier to round-trip through `state`.
    state = create_access_token(subject=str(current_user.id))
    return DocuSignAuthUrl(auth_url=build_docusign_authorization_url(state))


@router.get("/auth/docusign/callback", response_class=HTMLResponse)
def docusign_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(state)
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        refresh_token = exchange_docusign_code_for_refresh_token(code)
    except DocuSignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    integration = _get_integration(db, user.id, "docusign")
    if integration:
        integration.refresh_token = encrypt(refresh_token)
    else:
        integration = UserIntegration(user_id=user.id, provider="docusign", refresh_token=encrypt(refresh_token))
        db.add(integration)
    db.commit()

    log_action(db, "user_integration", user.id, "docusign_connected", user.email, {"provider": "docusign"})

    return "<html><body>DocuSign connected. You can close this tab and return to the app.</body></html>"


@router.get("/integrations/docusign/status", response_model=IntegrationStatus)
def docusign_status(
    user_id: uuid.UUID | None = Query(None, description="Check another user's status; defaults to the caller"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integration = _get_integration(db, user_id or current_user.id, "docusign")
    return IntegrationStatus(
        connected=integration is not None,
        connected_at=integration.connected_at if integration else None,
    )


@router.get("/integrations/linkedin/connect", response_model=LinkedInAuthUrl)
def connect_linkedin(current_user: User = Depends(get_current_user)):
    # Same JSON-not-redirect reasoning as Google/DocuSign's /connect. Standard
    # Authorization Code Grant, no PKCE.
    state = create_access_token(subject=str(current_user.id))
    return LinkedInAuthUrl(auth_url=build_linkedin_authorization_url(state))


@router.get("/auth/linkedin/callback", response_class=HTMLResponse)
def linkedin_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(state)
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        token_data = exchange_linkedin_code_for_access_token(code)
        member_urn = get_member_urn(token_data["access_token"])
    except LinkedInError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    expires_at = None
    if token_data.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    integration = _get_integration(db, user.id, "linkedin")
    if integration:
        integration.refresh_token = encrypt(token_data["access_token"])
        integration.expires_at = expires_at
        integration.provider_metadata = {"member_urn": member_urn}
    else:
        integration = UserIntegration(
            user_id=user.id,
            provider="linkedin",
            refresh_token=encrypt(token_data["access_token"]),
            expires_at=expires_at,
            provider_metadata={"member_urn": member_urn},
        )
        db.add(integration)
    db.commit()

    log_action(db, "user_integration", user.id, "linkedin_connected", user.email, {"provider": "linkedin"})

    return "<html><body>LinkedIn connected. You can close this tab and return to the app.</body></html>"


@router.get("/integrations/linkedin/status", response_model=IntegrationStatus)
def linkedin_status(
    user_id: uuid.UUID | None = Query(None, description="Check another user's status; defaults to the caller"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integration = _get_integration(db, user_id or current_user.id, "linkedin")
    expired = None
    if integration is not None:
        expired = integration.expires_at is not None and integration.expires_at < datetime.now(timezone.utc)
    return IntegrationStatus(
        connected=integration is not None,
        connected_at=integration.connected_at if integration else None,
        expired=expired,
    )
