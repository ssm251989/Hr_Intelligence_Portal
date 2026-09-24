from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.platform.tenancy.context import get_current_tenant
from app.schemas.auth import TokenResponse, UserLogin, UserRead, UserRegister

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
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    # Part 2: embeds which tenant this session was issued for (tid) -- get_current_user
    # rejects a token whose tid doesn't match the tenant this SAME request resolves to
    # (TenantResolverMiddleware, host/header-routed). Omitted (not an empty string) when no
    # tenant context is set (e.g. a test hitting create_access_token directly without going
    # through the middleware) -- get_current_user treats a missing tid as "nothing to check
    # yet", never as a mismatch, so this rolls out without touching every existing caller.
    tenant_ctx = get_current_tenant()
    extra_claims = {"tid": str(tenant_ctx.tenant_id)} if tenant_ctx else None
    token = create_access_token(subject=str(user.id), extra_claims=extra_claims)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
