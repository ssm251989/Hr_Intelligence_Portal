from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import USER_ROLES, UserRead

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
