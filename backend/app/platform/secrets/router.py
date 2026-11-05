"""Tenant secrets API (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 5) -- "set / rotate /
test"; never returns plaintext. Gated by require_roles("admin"), the interim stand-in for
the real permission code platform.secrets.manage until Part 5's IAM/RBAC exists.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.models.secret import Secret, SecretScope
from app.models.user import User
from app.platform.secrets.store import SecretAlreadyExistsError, SecretNotFoundError, get_secret_store
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/secrets", tags=["secrets"])


def _store(db: Session):
    tenant = require_current_tenant()
    return get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))


class SecretPut(BaseModel):
    ref: str
    value: str


class SecretRefResponse(BaseModel):
    ref: str
    status: str


@router.post("", response_model=SecretRefResponse, status_code=201)
def create_secret(payload: SecretPut, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    try:
        _store(db).put(payload.ref, payload.value, created_by=current_user.email)
    except SecretAlreadyExistsError:
        raise HTTPException(status_code=409, detail=f"Secret {payload.ref!r} already exists -- use rotate instead")
    return SecretRefResponse(ref=payload.ref, status="created")


class SecretRotateBody(BaseModel):
    value: str


@router.post("/{ref}/rotate", response_model=SecretRefResponse)
def rotate_secret(
    ref: str, payload: SecretRotateBody, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin")),
):
    try:
        _store(db).rotate(ref, payload.value, created_by=current_user.email)
    except SecretNotFoundError:
        raise HTTPException(status_code=404, detail=f"No such secret: {ref}")
    return SecretRefResponse(ref=ref, status="rotated")


@router.post("/{ref}/test", response_model=SecretRefResponse)
def test_secret(ref: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """Proves the secret round-trips through the store without ever putting the plaintext
    on the wire -- decrypts server-side and reports only whether that succeeded."""
    try:
        _store(db).get(ref)
    except SecretNotFoundError:
        raise HTTPException(status_code=404, detail=f"No such secret: {ref}")
    return SecretRefResponse(ref=ref, status="ok")


@router.delete("/{ref}", status_code=204)
def delete_secret(ref: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    _store(db).delete(ref)
