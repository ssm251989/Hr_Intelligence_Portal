"""Admin > Settings API (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4). Gated by
require_roles("admin") -- the interim stand-in for the real permission code
platform.settings.manage until Part 5's IAM/RBAC exists; every route below is meant to move
to that permission check unchanged once it does.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.models.user import User
from app.platform.settings.registry import UnknownSettingError, all_definitions, get_definition
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingDefinitionRead(BaseModel):
    key: str
    type: str
    default: Any
    module: str
    group: str
    label_i18n_key: str
    help_i18n_key: str
    scopes_allowed: list[str]
    sensitive: bool
    requires_restart: bool
    # Part 14 section 11: plain-language help + "what this affects" (see help_catalog.py)
    help: Optional[str] = None
    affects: Optional[str] = None
    affects_i18n_key: Optional[str] = None


class SettingValueRead(BaseModel):
    key: str
    value: Any
    scope_type: str
    scope_id: Optional[UUID]


class SettingValueUpdate(BaseModel):
    value: Any
    scope_type: str = "tenant"
    scope_id: Optional[UUID] = None


class SettingHistoryEntry(BaseModel):
    value: Any
    version: int
    updated_by: Optional[str]
    updated_at: Optional[datetime]
    scope_type: str
    scope_id: Optional[UUID]


def _to_def_read(d) -> SettingDefinitionRead:
    from app.platform.settings.help_catalog import help_for

    info = help_for(d.key) or {}
    return SettingDefinitionRead(
        key=d.key, type=d.type, default=d.default, module=d.module, group=d.group,
        label_i18n_key=d.label_i18n_key, help_i18n_key=d.help_i18n_key or info.get("help_i18n_key", ""),
        scopes_allowed=list(d.scopes_allowed), sensitive=d.sensitive, requires_restart=d.requires_restart,
        help=info.get("help"), affects=info.get("affects"), affects_i18n_key=info.get("affects_i18n_key"),
    )


@router.get("/definitions", response_model=list[SettingDefinitionRead])
def list_definitions(module: Optional[str] = None, current_user: User = Depends(require_roles("admin"))):
    return [_to_def_read(d) for d in all_definitions(module=module)]


@router.get("", response_model=list[SettingValueRead])
def list_settings(
    prefix: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    ctx = SettingContext(tenant=require_current_tenant())
    service = SettingsService(db)
    values = service.get_many(prefix, ctx)
    return [SettingValueRead(key=key, value=value, scope_type="tenant", scope_id=None) for key, value in values.items()]


@router.put("/{key}", response_model=SettingValueRead)
def update_setting(
    key: str,
    payload: SettingValueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    try:
        get_definition(key)
    except UnknownSettingError:
        raise HTTPException(status_code=404, detail=f"No such setting: {key}")

    tenant = require_current_tenant()
    service = SettingsService(db)
    try:
        row = service.set(
            key, payload.value, scope_type=payload.scope_type, scope_id=payload.scope_id,
            actor=current_user.email, tenant=tenant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SettingValueRead(key=row.key, value=row.value_json, scope_type=row.scope_type, scope_id=row.scope_id)


@router.get("/{key}/history", response_model=list[SettingHistoryEntry])
def setting_history(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    try:
        get_definition(key)
    except UnknownSettingError:
        raise HTTPException(status_code=404, detail=f"No such setting: {key}")

    ctx = SettingContext(tenant=require_current_tenant())
    service = SettingsService(db)
    return [
        SettingHistoryEntry(
            value=row.value_json, version=row.version, updated_by=row.updated_by,
            updated_at=row.updated_at, scope_type=row.scope_type, scope_id=row.scope_id,
        )
        for row in service.history(key, ctx)
    ]


@router.post("/export")
def export_settings(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """A settings-only export (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4's "configuration
    pack" also bundles masters/templates/workflows -- none of those exist yet, Parts 4-6;
    this covers what Part 2 actually has). Never includes a "secret_ref"-typed setting's
    resolved value -- secrets are exported/rotated through platform.secrets's own API, never
    embedded in a settings bundle."""
    ctx = SettingContext(tenant=require_current_tenant())
    service = SettingsService(db)
    bundle = {}
    for d in all_definitions():
        if d.type == "secret_ref":
            continue
        bundle[d.key] = service.get(d.key, ctx)
    return {"settings": bundle}


class SettingsImportRequest(BaseModel):
    settings: dict[str, Any]


@router.post("/import")
def import_settings(
    payload: SettingsImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    tenant = require_current_tenant()
    service = SettingsService(db)
    imported: list[str] = []
    skipped: list[dict] = []
    for key, value in payload.settings.items():
        try:
            get_definition(key)
        except UnknownSettingError:
            skipped.append({"key": key, "reason": "unknown setting"})
            continue
        try:
            service.set(key, value, scope_type="tenant", scope_id=None, actor=current_user.email, tenant=tenant)
            imported.append(key)
        except ValueError as exc:
            skipped.append({"key": key, "reason": str(exc)})
    return {"imported": imported, "skipped": skipped}


class SettingRevertRequest(BaseModel):
    version: int
    scope_type: str = "tenant"
    scope_id: Optional[UUID] = None


@router.post("/{key}/revert", response_model=SettingValueRead)
def revert_setting(key: str, payload: SettingRevertRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """Part 14 section 7 / L-A2 ("change history with revert"): re-applies an earlier
    version's value as a NEW version -- history is never rewritten."""
    try:
        get_definition(key)
    except UnknownSettingError:
        raise HTTPException(status_code=404, detail=f"No such setting: {key}")
    tenant = require_current_tenant()
    service = SettingsService(db)
    entry = next((h for h in service.history(key, SettingContext(tenant=tenant)) if h.version == payload.version and h.scope_type == payload.scope_type), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No version {payload.version} in this setting's history")
    try:
        row = service.set(key, entry.value_json, scope_type=payload.scope_type, scope_id=payload.scope_id, actor=f"{current_user.email} (revert to v{payload.version})", tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SettingValueRead(key=row.key, value=row.value_json, scope_type=row.scope_type, scope_id=row.scope_id)
