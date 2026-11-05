from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.platform.iam.roles import bridge_single_user
from app.platform.tenancy.context import get_current_tenant
from app.schemas.auth import USER_ROLES, AdminUserCreate, UserRead

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserRead])
def list_users(
    role: Optional[str] = Query(None, description=f"Filter by role, one of {USER_ROLES}"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    return query.order_by(User.full_name, User.email).all()


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
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

    # Part 5A: immediately covered by the new authz system too (bridge_single_user's own
    # docstring explains why this happens at creation, not lazily inside a permission
    # check) -- a no-op when there's no tenant context to bridge into.
    tenant_ctx = get_current_tenant()
    if tenant_ctx is not None:
        bridge_single_user(db, tenant_ctx, user)

    return user
