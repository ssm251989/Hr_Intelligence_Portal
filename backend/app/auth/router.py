from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_user_for_mfa_enrollment
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.iam import UserDevice
from app.models.user import User
from app.platform.iam import mfa, sessions
from app.platform.iam.roles import bridge_single_user
from app.platform.tenancy.context import get_current_tenant
from app.schemas.auth import (
    DeviceRead,
    LoginResponse,
    MfaVerifyRequest,
    RefreshRequest,
    TotpEnrollConfirmRequest,
    TotpEnrollConfirmResponse,
    TotpEnrollStartResponse,
    UserLogin,
    UserRead,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    tenant_ctx = get_current_tenant()
    if tenant_ctx is not None:
        bridge_single_user(db, tenant_ctx, user)

    return user


def _client_ip(request: Optional[Request]) -> Optional[str]:
    return request.client.host if request is not None and request.client else None


@router.post("/login", response_model=LoginResponse)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    """Part 5A section 1's multi-step login. Every check below that needs a tenant
    (lockout, IP allow-list, MFA) is skipped entirely when no tenant context is set --
    the same graceful-degradation `get_current_tenant()` already documented for the `tid`
    claim, so every existing test/helper that calls this without going through
    TenantResolverMiddleware keeps working exactly as before Part 5."""
    tenant_ctx = get_current_tenant()
    ip_address = _client_ip(request)

    if tenant_ctx is not None and not sessions.is_ip_allowed(db, tenant_ctx, ip_address):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This IP address is not allowed to sign in")

    user = db.query(User).filter(User.email == payload.email).first()

    if tenant_ctx is not None and user is not None and sessions.is_locked_out(user):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account is temporarily locked. Try again later.")

    if not user or not verify_password(payload.password, user.hashed_password):
        if tenant_ctx is not None and user is not None:
            sessions.record_failed_login(db, tenant_ctx, user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if tenant_ctx is not None:
        sessions.reset_failed_logins(db, user)

    extra_claims = {"tid": str(tenant_ctx.tenant_id)} if tenant_ctx else None

    if tenant_ctx is None or not mfa.is_mfa_required(db, tenant_ctx):
        return _issue_full_session(db, tenant_ctx, user, request, payload, extra_claims)

    if not mfa.is_mfa_enrolled(user):
        enrollment_claims = {**(extra_claims or {}), "purpose": "mfa_enrollment"}
        enrollment_token = create_access_token(subject=str(user.id), extra_claims=enrollment_claims)
        return LoginResponse(mfa_enrollment_required=True, mfa_enrollment_token=enrollment_token)

    device = _find_remembered_device(db, tenant_ctx, user, request)
    if device is not None:
        return _issue_full_session(db, tenant_ctx, user, request, payload, extra_claims, device=device)

    methods = (["totp"] if user.mfa_totp_enrolled_at else []) + (["email_otp"] if user.mfa_email_otp_enabled else [])
    challenge = mfa.create_totp_challenge(db, tenant_ctx, user) if "totp" in methods else mfa.send_email_otp_challenge(db, tenant_ctx, user)
    # No token is minted for this step -- /auth/mfa/verify below identifies the pending
    # challenge purely by challenge.id (itself only resolvable server-side, tenant-scoped,
    # single-use), so there's nothing a bearer token would add here that the challenge_id
    # doesn't already provide.
    return LoginResponse(mfa_required=True, mfa_challenge_id=challenge.id, mfa_methods=methods)


def _find_remembered_device(db: Session, tenant_ctx, user: User, request: Request) -> Optional[UserDevice]:
    device_id = request.headers.get("X-Device-Id")
    if not device_id:
        return None
    try:
        device = db.get(UserDevice, UUID(device_id))
    except ValueError:
        return None
    if device is None or device.tenant_id != tenant_ctx.tenant_id or device.user_id != user.id:
        return None
    return device if sessions.is_device_mfa_remembered(device) else None


def _issue_full_session(db: Session, tenant_ctx, user: User, request: Request, payload: UserLogin, extra_claims, device: Optional[UserDevice] = None) -> LoginResponse:
    token = create_access_token(subject=str(user.id), extra_claims=extra_claims)
    if tenant_ctx is None:
        return LoginResponse(access_token=token, token_type="bearer")

    if device is None:
        device = sessions.get_or_create_device(db, tenant_ctx, user, user_agent=request.headers.get("User-Agent"), ip_address=_client_ip(request))
        if payload.device_label:
            device.label = payload.device_label
            db.commit()
        if payload.remember_device:
            sessions.remember_device(db, tenant_ctx, device)

    refresh_plaintext, _row = sessions.issue_refresh_token(db, tenant_ctx, user, device)
    return LoginResponse(access_token=token, token_type="bearer", refresh_token=refresh_plaintext, device_id=device.id)


@router.post("/refresh", response_model=LoginResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    tenant_ctx = get_current_tenant()
    if tenant_ctx is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tenant context to refresh a session in")
    try:
        new_plaintext, new_row, user = sessions.rotate_refresh_token(db, tenant_ctx, payload.refresh_token)
    except sessions.InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    token = create_access_token(subject=str(user.id), extra_claims={"tid": str(tenant_ctx.tenant_id)})
    return LoginResponse(access_token=token, token_type="bearer", refresh_token=new_plaintext, device_id=new_row.device_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    tenant_ctx = get_current_tenant()
    if tenant_ctx is None:
        return
    try:
        row = sessions.rotate_refresh_token(db, tenant_ctx, payload.refresh_token)[1]
        sessions.revoke_refresh_token_by_id(db, tenant_ctx, row.id)
    except sessions.InvalidRefreshTokenError:
        pass


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ---- sessions / devices ----


@router.get("/sessions", response_model=list[DeviceRead])
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    return sessions.list_devices(db, require_current_tenant(), current_user)


@router.delete("/sessions/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(device_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    tenant_ctx = require_current_tenant()
    device = db.get(UserDevice, device_id)
    if device is not None and device.user_id == current_user.id:
        sessions.revoke_device(db, tenant_ctx, device_id)


# ---- MFA: self-service enrollment + login-time verification ----


@router.post("/mfa/enroll/totp/start", response_model=TotpEnrollStartResponse)
def start_totp(current_user: User = Depends(get_user_for_mfa_enrollment), db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    secret, uri = mfa.start_totp_enrollment(db, require_current_tenant(), current_user)
    return TotpEnrollStartResponse(secret=secret, provisioning_uri=uri)


@router.post("/mfa/enroll/totp/confirm", response_model=TotpEnrollConfirmResponse)
def confirm_totp(payload: TotpEnrollConfirmRequest, current_user: User = Depends(get_user_for_mfa_enrollment), db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    try:
        codes = mfa.confirm_totp_enrollment(db, require_current_tenant(), current_user, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return TotpEnrollConfirmResponse(recovery_codes=codes)


@router.post("/mfa/enroll/email-otp", status_code=status.HTTP_204_NO_CONTENT)
def enroll_email_otp(current_user: User = Depends(get_user_for_mfa_enrollment), db: Session = Depends(get_db)):
    current_user.mfa_email_otp_enabled = True
    db.commit()


@router.post("/mfa/verify", response_model=LoginResponse)
def verify_mfa(payload: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    tenant_ctx = require_current_tenant()
    user = mfa.verify_challenge(db, tenant_ctx, payload.challenge_id, payload.code)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect or expired code")

    extra_claims = {"tid": str(tenant_ctx.tenant_id)}
    fake_payload = UserLogin(email=user.email, password="", device_label=payload.device_label, remember_device=payload.remember_device)
    return _issue_full_session(db, tenant_ctx, user, request, fake_payload, extra_claims)
