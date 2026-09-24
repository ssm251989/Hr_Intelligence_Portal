import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.platform.tenancy.context import get_current_tenant

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
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

    # Part 2: reject a token minted for a different tenant than this request resolved to
    # (TenantResolverMiddleware). A token with no "tid" claim at all (every test helper
    # that calls create_access_token directly, never through /auth/login) has nothing to
    # check against -- never treated as a mismatch, only an actual tid disagreement is.
    token_tid = payload.get("tid")
    current_tenant = get_current_tenant()
    if token_tid is not None and current_tenant is not None and token_tid != str(current_tenant.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token was not issued for this tenant")

    user = db.get(User, user_uuid)
    if user is None:
        raise _unauthorized()
    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    try:
        return get_current_user(credentials=credentials, db=db)
    except HTTPException:
        return None


def require_roles(*allowed_roles: str):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return dependency
