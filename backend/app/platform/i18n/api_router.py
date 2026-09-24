"""i18n API (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 6) -- the bundle endpoint
frontend i18next loads as its own backend, plus override CRUD."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.metadata import I18nOverride
from app.models.user import User
from app.platform.i18n import service as i18n_service
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])
public_router = APIRouter(prefix="/api/v1/public/i18n", tags=["i18n-public"])


@public_router.get("/{locale}")
def get_bundle(locale: str, db: Session = Depends(get_db)):
    """Public -- a login page (pre-auth) still needs translated labels."""
    tenant = require_current_tenant()
    return i18n_service.merged_bundle(db, tenant, locale)


class OverrideUpsert(BaseModel):
    locale: str
    key: str
    value: str


class OverrideRead(BaseModel):
    id: UUID
    locale: str
    key: str
    value: str


@router.get("/overrides", response_model=list[OverrideRead])
def list_overrides(locale: str, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    tenant = require_current_tenant()
    rows = db.query(I18nOverride).filter(I18nOverride.tenant_id == tenant.tenant_id, I18nOverride.locale == locale).all()
    return [OverrideRead(id=r.id, locale=r.locale, key=r.key, value=r.value) for r in rows]


@router.put("/overrides", response_model=OverrideRead)
def set_override(payload: OverrideUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    row = i18n_service.set_override(db, tenant, payload.locale, payload.key, payload.value)
    return OverrideRead(id=row.id, locale=row.locale, key=row.key, value=row.value)


@router.delete("/overrides/{override_id}", status_code=204)
def delete_override(override_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    i18n_service.delete_override(db, tenant, override_id)
