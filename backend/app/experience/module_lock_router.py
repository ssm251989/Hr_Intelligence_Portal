"""Part 18.4 API: module unlock passcode (app/platform/module_lock.py).

- GET  /api/v1/modules/access           which modules are locked (any signed-in user; the menu uses bootstrap)
- POST /api/v1/modules/access/unlock    {module | "__all__", passcode}      admins
- POST /api/v1/modules/access/lock      {module | "__all__"}                admins
- POST /api/v1/modules/access/passcode  {current, new, module?}             admins, needs the current passcode
Never locked itself (ModuleLockMiddleware EXEMPT).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform import module_lock
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/modules/access", tags=["module-lock"])


class UnlockBody(BaseModel):
    module: str = Field(max_length=50)
    passcode: str = Field(max_length=200)


class LockBody(BaseModel):
    module: str = Field(max_length=50)


class PasscodeBody(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)
    module: Optional[str] = Field(default=None, max_length=50)


def _admin(db, user):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, "platform.settings.configure"):
        raise HTTPException(status_code=403, detail="Only an admin can unlock or lock modules.")
    return tenant


def _raise(exc: module_lock.LockError):
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("")
def access_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    return {**module_lock.status(db, tenant), "can_unlock": has_permission(db, tenant, current_user, "platform.settings.configure")}


@router.post("/unlock")
def unlock(body: UnlockBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    try:
        return module_lock.unlock(db, tenant, body.module, body.passcode, actor=current_user.email)
    except module_lock.LockError as exc:
        _raise(exc)


@router.post("/lock")
def lock(body: LockBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    return module_lock.lock(db, tenant, body.module, actor=current_user.email)


@router.post("/passcode")
def change_passcode(body: PasscodeBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _admin(db, current_user)
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Only the main admin can change the module passcode.")
    try:
        module_lock.set_passcode(db, tenant, body.new, actor=current_user.email, key=body.module or module_lock.ALL, current=body.current)
    except module_lock.LockError as exc:
        _raise(exc)
    return {"changed": True}
