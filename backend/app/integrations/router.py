import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from jose import JWTError
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.crypto import encrypt
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token
from app.integrations.google_calendar import (
    GoogleCalendarError,
    build_authorization_url,
    exchange_code_for_refresh_token,
    generate_code_verifier,
)
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.schemas.integration import GoogleAuthUrl, IntegrationStatus

router = APIRouter(tags=["integrations"])


def _get_integration(db: Session, user_id: uuid.UUID) -> UserIntegration | None:
    return (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == user_id, UserIntegration.provider == "google")
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

    integration = _get_integration(db, user.id)
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
    integration = _get_integration(db, user_id or current_user.id)
    return IntegrationStatus(
        connected=integration is not None,
        connected_at=integration.connected_at if integration else None,
    )
