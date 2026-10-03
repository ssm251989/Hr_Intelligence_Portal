"""Part 19.1 / 19.2 API: "Choose what you use" (Setup and Settings > Company > Modules).

- GET  /api/v1/modules                every module card: status active / pending / off, needs,
                                      the open activation request (no code, ever)
- POST /api/v1/modules/request        {modules, with_needs} -> waiting for the activation code;
                                      the code is emailed to CTD Techs, not to the company
- POST /api/v1/modules/activate       {code} -> the requested modules become active
- POST /api/v1/modules/off            {modules, with_dependents} -> off straight away, no code

Never blocked by the module gate itself (module_registry.EXEMPT). Changing modules needs
platform.settings.configure; anyone signed in may read the list.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform import activation, module_status
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/modules", tags=["modules"])


def _raise(exc) -> None:
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc), **getattr(exc, "extra", {})})


def _state(db: Session, user: User) -> dict:
    tenant = require_current_tenant()
    return {"modules": module_status.status(db, tenant), "request": activation.open_request(tenant),
            "can_manage": has_permission(db, tenant, user, "platform.settings.configure")}


@router.get("")
def list_modules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _state(db, current_user)


class RequestIn(BaseModel):
    modules: list[str] = Field(min_length=1, max_length=20)
    with_needs: bool = False


@router.post("/request")
def request_activation(body: RequestIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        info = activation.request_activation(db, require_current_tenant(), body.modules, current_user, with_needs=body.with_needs)
    except activation.ActivationError as exc:
        _raise(exc)
    return {**_state(db, current_user), "requested": info}


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


@router.post("/activate")
def activate(body: CodeIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        done = activation.activate_with_code(db, require_current_tenant(), body.code, current_user)
    except activation.ActivationError as exc:
        _raise(exc)
    return {**_state(db, current_user), **done}


@router.post("/request/resend")
def resend_request(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    """[Resend request] / [Try sending again] -- cooldown and a daily limit (platform settings)."""
    try:
        info = activation.resend_request(db, require_current_tenant(), current_user)
    except activation.ActivationError as exc:
        _raise(exc)
    return {**_state(db, current_user), "resent": info}


@router.post("/request/cancel")
def cancel_request(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    """[Cancel request] -- the waiting modules go back to Off."""
    try:
        activation.cancel_request(db, require_current_tenant(), current_user)
    except activation.ActivationError as exc:
        _raise(exc)
    return _state(db, current_user)


class OffIn(BaseModel):
    modules: list[str] = Field(min_length=1, max_length=20)
    with_dependents: bool = False


@router.post("/off")
def switch_off(body: OffIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        done = module_status.switch_off(db, require_current_tenant(), body.modules, current_user.email, with_dependents=body.with_dependents)
    except module_status.ModuleError as exc:
        _raise(exc)
    return {**_state(db, current_user), "switched_off": done}
