"""Metadata API (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 1-4) -- custom field defs,
form layouts, masters, sequences. Gated by `authz.require(...)` (Part 5), same pattern as
`platform.iam.api_router`/`platform.workflow.api_router`.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.metadata import CustomFieldDef, EXTENSIBLE_ENTITIES, MasterType
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.metadata import forms as forms_service
from app.platform.metadata import masters as masters_service
from app.platform.metadata import sequences as sequences_service
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/metadata", tags=["metadata"])


# ---- custom field defs ----


class CustomFieldDefUpsert(BaseModel):
    entity: str
    code: str
    label_i18n: dict = {}
    type: str
    validation_json: Optional[dict] = None
    default: Optional[object] = None
    required_condition_jsonlogic: Optional[dict] = None
    visible_condition_jsonlogic: Optional[dict] = None
    section: Optional[str] = None
    order: int = 0
    sensitive: bool = False
    searchable: bool = False
    reportable: bool = True


class CustomFieldDefRead(BaseModel):
    id: UUID
    entity: str
    code: str
    label_i18n: dict
    type: str
    validation_json: Optional[dict]
    default: Optional[object]
    section: Optional[str]
    order: int
    sensitive: bool
    is_active: bool


def _def_read(d: CustomFieldDef) -> CustomFieldDefRead:
    return CustomFieldDefRead(
        id=d.id, entity=d.entity, code=d.code, label_i18n=d.label_i18n, type=d.type, validation_json=d.validation_json,
        default=d.default, section=d.section, order=d.order, sensitive=d.sensitive, is_active=d.is_active,
    )


@router.get("/custom-fields", response_model=list[CustomFieldDefRead])
def list_custom_field_defs(entity: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    tenant = require_current_tenant()
    query = db.query(CustomFieldDef).filter(CustomFieldDef.tenant_id == tenant.tenant_id)
    if entity is not None:
        query = query.filter(CustomFieldDef.entity == entity)
    return [_def_read(d) for d in query.order_by(CustomFieldDef.entity, CustomFieldDef.section, CustomFieldDef.order).all()]


@router.post("/custom-fields", response_model=CustomFieldDefRead, status_code=201)
def create_custom_field_def(payload: CustomFieldDefUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    if payload.entity not in EXTENSIBLE_ENTITIES:
        raise HTTPException(status_code=400, detail=f"entity must be one of {EXTENSIBLE_ENTITIES}")
    tenant = require_current_tenant()
    row = CustomFieldDef(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _def_read(row)


@router.patch("/custom-fields/{def_id}", response_model=CustomFieldDefRead)
def update_custom_field_def(def_id: UUID, is_active: Optional[bool] = None, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    row = db.get(CustomFieldDef, def_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Custom field not found")
    if is_active is not None:
        row.is_active = is_active
    db.commit()
    db.refresh(row)
    return _def_read(row)


@router.delete("/custom-fields/{def_id}", status_code=204)
def delete_custom_field_def(def_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    row = db.get(CustomFieldDef, def_id)
    if row is not None:
        db.delete(row)
        db.commit()


# ---- form layouts ----


class LayoutUpsert(BaseModel):
    entity: str
    context: str
    sections: list = []
    role_ids: Optional[list[UUID]] = None


@router.get("/form-layouts/{entity}/{context}")
def get_effective_layout(entity: str, context: str, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    tenant = require_current_tenant()
    return forms_service.get_effective_layout(db, tenant, entity, context)


@router.put("/form-layouts")
def upsert_form_layout(payload: LayoutUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    layout = forms_service.upsert_layout(db, tenant, entity=payload.entity, context=payload.context, sections=payload.sections, role_ids=payload.role_ids)
    return {"id": str(layout.id), "entity": layout.entity, "context": layout.context, "sections": layout.sections_json}


# ---- masters ----


class MasterTypeRead(BaseModel):
    code: str
    name: str
    hierarchical: bool


class MasterValueCreate(BaseModel):
    code: str
    label_i18n: dict
    parent_id: Optional[UUID] = None
    attributes: dict = {}
    sort: int = 0


class MasterValueRead(BaseModel):
    id: UUID
    type_code: str
    code: str
    label_i18n: dict
    parent_id: Optional[UUID]
    sort: int
    is_active: bool


def _value_read(v) -> MasterValueRead:
    return MasterValueRead(id=v.id, type_code=v.type_code, code=v.code, label_i18n=v.label_i18n, parent_id=v.parent_id, sort=v.sort, is_active=v.is_active)


@router.get("/master-types", response_model=list[MasterTypeRead])
def list_master_types(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    masters_service.register_master_types(db)
    return [MasterTypeRead(code=t.code, name=t.name, hierarchical=t.hierarchical) for t in db.query(MasterType).order_by(MasterType.code).all()]


@router.get("/master-values/{type_code}", response_model=list[MasterValueRead])
def list_master_values(type_code: str, include_inactive: bool = False, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    tenant = require_current_tenant()
    return [_value_read(v) for v in masters_service.list_values(db, tenant, type_code, include_inactive=include_inactive)]


@router.post("/master-values/{type_code}", response_model=MasterValueRead, status_code=201)
def create_master_value(type_code: str, payload: MasterValueCreate, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    value = masters_service.create_value(
        db, tenant, type_code=type_code, code=payload.code, label_i18n=payload.label_i18n,
        parent_id=payload.parent_id, attributes=payload.attributes, sort=payload.sort,
    )
    return _value_read(value)


@router.delete("/master-values/{value_id}", status_code=204)
def deactivate_master_value(value_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    masters_service.deactivate_value(db, tenant, value_id)


# ---- sequences ----


class SequenceDefine(BaseModel):
    key: str
    pattern: str
    scope: Optional[str] = None
    reset: str = "never"


@router.post("/sequences", status_code=201)
def define_sequence(payload: SequenceDefine, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    row = sequences_service.define(db, tenant, key=payload.key, pattern=payload.pattern, scope=payload.scope, reset=payload.reset)
    return {"id": str(row.id), "key": row.key, "pattern": row.pattern, "current": row.current}


@router.post("/sequences/{key}/next")
def get_next_value(key: str, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    tenant = require_current_tenant()
    try:
        return {"value": sequences_service.next_value(db, tenant, key)}
    except sequences_service.SequenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
