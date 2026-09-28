import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.platform.tenancy.context import get_current_tenant

bearer_scheme = HTTPBearer(auto_error=False)

# Part 15.6: an agency login (flat role "agency") belongs to an OUTSIDE company. Several
# older endpoints only check "is signed in", so rather than trust each one, an agency user
# is refused everywhere except these path prefixes: their own portal, their session, and
# the app shell (menu/branding/notifications/preferences).
AGENCY_ALLOWED_PREFIXES = ("/auth/", "/api/me/", "/api/v1/me/preferences", "/api/v1/agency-portal")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if user_id is None:
            raise _unauthorized()
        user_uuid = uuid.UUID(user_id)
    except (JWTError, ValueError):
        raise _unauthorized()

    # Part 5A: a "purpose"-carrying token (mfa_challenge / mfa_enrollment -- see
    # auth/router.py's login()) is a narrow-scope, short-lived token for ONE specific
    # next step, never a full session -- get_current_user is the dependency every real
    # endpoint uses, so it must reject these outright rather than silently accepting them
    # as a logged-in session just because they happen to carry a valid `sub`.
    if payload.get("purpose") is not None:
        raise _unauthorized()

    # Part 2: reject a token minted for a different tenant than this request resolved to
    # (TenantResolverMiddleware). A token with no "tid" claim at all (every test helper
    # that calls create_access_token directly, never through /auth/login) has nothing to
    # check against -- never treated as a mismatch, only an actual tid disagreement is.
    token_tid = payload.get("tid")
    current_tenant = get_current_tenant()
    if token_tid is not None and current_tenant is not None and token_tid != str(current_tenant.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token was not issued for this tenant")

    # Part 13: a platform impersonation token dies the moment its session is ended from
    # the console, not only at its (already short) expiry.
    if payload.get("imp"):
        from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
        from app.platform.tenancy.models_cp import ImpersonationSession

        cp_db = ControlPlaneSessionLocal()
        try:
            session = cp_db.get(ImpersonationSession, uuid.UUID(payload["imp"]))
            if session is None or session.ended_at is not None:
                raise _unauthorized()
        finally:
            cp_db.close()

    user = db.get(User, user_uuid)
    if user is None or getattr(user, "deactivated_at", None) is not None:  # Part 18.22: deactivated = signed out everywhere
        raise _unauthorized()
    if user.role == "agency" and not request.url.path.startswith(AGENCY_ALLOWED_PREFIXES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agency accounts can only use the agency portal")
    return user


def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    try:
        return get_current_user(request=request, credentials=credentials, db=db)
    except HTTPException:
        return None


def get_user_for_mfa_enrollment(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Accepts EITHER a normal full-session token (a user enrolling voluntarily, self-
    service, any time after login) OR a `purpose="mfa_enrollment"` token (minted by
    login() when iam.auth.mfa_required is on and this user hasn't enrolled yet -- they
    must complete enrollment before a real session token is ever issued). Rejects a
    `purpose="mfa_challenge"` token -- that one is only for /auth/mfa/verify, never for
    starting/confirming enrollment."""
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if user_id is None:
            raise _unauthorized()
        user_uuid = uuid.UUID(user_id)
    except (JWTError, ValueError):
        raise _unauthorized()

    purpose = payload.get("purpose")
    if purpose is not None and purpose != "mfa_enrollment":
        raise _unauthorized()

    user = db.get(User, user_uuid)
    if user is None:
        raise _unauthorized()
    return user


def require_roles(*allowed_roles: str):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return dependency
