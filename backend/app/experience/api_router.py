"""Part 14 API (docs/HRMS_COMPLETE_SPEC.txt Part 14): setup wizard, configuration health,
global search, unified inbox, saved list views, autosaved form drafts, version history +
revert, and the caller's own preferences / letters / documents (the PWA caches the last
two for offline reading)."""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.experience import config_health, inbox, search, setup_wizard, versioning
from app.models.experience import FormDraft, SavedView
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1", tags=["experience"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---- setup wizard ----


@router.get("/setup/progress")
def setup_progress(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    return setup_wizard.progress(db, require_current_tenant())


class CompanyStep(BaseModel):
    display_name: str
    legal_name: Optional[str] = None
    timezone: str
    locale: Optional[str] = None
    currency: Optional[str] = None


@router.post("/setup/company")
def setup_company(payload: CompanyStep, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return setup_wizard.set_company(db, require_current_tenant(), actor=current_user.email, **payload.model_dump())
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


class ModulesStep(BaseModel):
    modules: list[str]


@router.post("/setup/modules")
def setup_modules(payload: ModulesStep, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return setup_wizard.set_modules(db, require_current_tenant(), payload.modules, actor=current_user.email)
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


class ConfigPackStep(BaseModel):
    pack: dict
    dry_run: bool = True


@router.post("/setup/config-pack")
def setup_config_pack(payload: ConfigPackStep, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return setup_wizard.apply_config_pack(db, require_current_tenant(), payload.pack, actor=current_user.email, dry_run=payload.dry_run)
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


class InviteAdmin(BaseModel):
    email: str
    full_name: Optional[str] = None


@router.post("/setup/invite-admin", status_code=201)
def setup_invite_admin(payload: InviteAdmin, db: Session = Depends(get_db), current_user: User = Depends(require("platform.users.create"))):
    try:
        return setup_wizard.invite_admin(db, require_current_tenant(), actor=current_user.email, **payload.model_dump())
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


class SkipStep(BaseModel):
    undo: bool = False


# ---- Part 17.10: saved values, first office, employees file, ready-made templates ----


@router.get("/setup/values")
def setup_values(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    return setup_wizard.values(db, require_current_tenant())


class EntityLocationStep(BaseModel):
    entity_name: str
    location_name: str
    city: Optional[str] = None
    state: Optional[str] = None


@router.post("/setup/entities-locations")
def setup_entities(payload: EntityLocationStep, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return setup_wizard.add_entity_location(db, require_current_tenant(), actor=current_user.email, **payload.model_dump())
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


from fastapi import File, Form, UploadFile  # noqa: E402


@router.post("/setup/employees-file")
async def setup_employees_file(file: UploadFile = File(...), commit: bool = Form(False), db: Session = Depends(get_db),
                               current_user: User = Depends(require("platform.settings.configure"))):
    """commit=false -> check the file (rows + errors); commit=true -> add the valid people."""
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="That file is larger than 10 MB.")
    try:
        return setup_wizard.import_employees(db, require_current_tenant(), data, file.filename or "", commit=commit, actor=current_user.email)
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


@router.get("/setup/employees-sample")
def setup_employees_sample(current_user: User = Depends(require("platform.settings.view"))):
    from fastapi.responses import Response

    body = "first_name,last_name,personal_email,personal_phone,employee_code,status,worker_type\n" \
           "Asha,Verma,asha.verma@example.com,9876543210,,active,employee\n"
    return Response(content=body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="employees-sample.csv"'})


@router.get("/setup/templates")
def setup_templates_list(current_user: User = Depends(require("platform.settings.view"))):
    from app.experience import setup_templates

    return [setup_templates.preview(t["key"]) for t in setup_templates.listing()]


@router.post("/setup/templates/{key}/apply")
def setup_template_apply(key: str, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    from app.experience import setup_templates

    if key not in setup_templates.TEMPLATES:
        raise HTTPException(status_code=404, detail="Unknown template")
    result = setup_templates.apply(db, require_current_tenant(), key, actor=current_user.email)
    return {**result, "progress": setup_wizard.progress(db, require_current_tenant())}


@router.post("/setup/steps/{step}/skip")
def setup_skip(step: str, payload: SkipStep, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return setup_wizard.skip(db, require_current_tenant(), step, actor=current_user.email, undo=payload.undo)
    except setup_wizard.SetupError as exc:
        raise _bad(exc)


@router.get("/setup/config-health")
def setup_config_health(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.view"))):
    return config_health.check(db, require_current_tenant())


# ---- search + inbox ----


@router.get("/search")
def global_search(q: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return search.search(db, require_current_tenant(), current_user, q)


@router.get("/inbox/all")
def unified_inbox_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return inbox.items_for(db, require_current_tenant(), current_user)


# ---- saved views ----


class ViewSave(BaseModel):
    name: str
    config: dict
    is_default: bool = False
    shared_role_name: Optional[str] = None


def _view_dict(v: SavedView, user: User) -> dict:
    return {"id": str(v.id), "name": v.name, "config": v.config_json, "is_default": v.is_default, "shared_role_name": v.shared_role_name, "mine": v.user_id == user.id}


@router.get("/views/{list_key}")
def list_views(list_key: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.platform.iam.roles import role_names_for

    tenant = require_current_tenant()
    roles = set(role_names_for(db, tenant, current_user))
    rows = db.query(SavedView).filter(SavedView.tenant_id == tenant.tenant_id, SavedView.list_key == list_key).order_by(SavedView.name).all()
    return [_view_dict(v, current_user) for v in rows if v.user_id == current_user.id or (v.shared_role_name and v.shared_role_name in roles)]


@router.put("/views/{list_key}")
def save_view(list_key: str, payload: ViewSave, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    if payload.shared_role_name and not has_permission(db, tenant, current_user, "platform.settings.configure"):
        raise HTTPException(status_code=403, detail="Only admins can share a view with a role")
    row = db.query(SavedView).filter(SavedView.tenant_id == tenant.tenant_id, SavedView.user_id == current_user.id, SavedView.list_key == list_key,
                                     SavedView.name == payload.name).first()
    if row is None:
        row = SavedView(tenant_id=tenant.tenant_id, user_id=current_user.id, list_key=list_key, name=payload.name)
        db.add(row)
    if payload.is_default:
        db.query(SavedView).filter(SavedView.tenant_id == tenant.tenant_id, SavedView.user_id == current_user.id, SavedView.list_key == list_key).update({"is_default": False})
    row.config_json, row.is_default, row.shared_role_name = payload.config, payload.is_default, payload.shared_role_name
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _view_dict(row, current_user)


@router.delete("/views/{list_key}/{view_id}", status_code=204)
def delete_view(list_key: str, view_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    row = db.query(SavedView).filter(SavedView.tenant_id == tenant.tenant_id, SavedView.user_id == current_user.id, SavedView.id == view_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="View not found")
    db.delete(row)  # a user's own UI preference, not business data
    db.commit()


# ---- autosaved drafts ----


class DraftSave(BaseModel):
    data: dict


@router.get("/drafts/{form_key}")
def get_draft(form_key: str, entity_ref: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    row = db.query(FormDraft).filter(FormDraft.tenant_id == tenant.tenant_id, FormDraft.user_id == current_user.id, FormDraft.form_key == form_key,
                                     FormDraft.entity_ref == entity_ref).first()
    return {"data": row.data_json, "updated_at": row.updated_at.isoformat() if row.updated_at else None} if row else {"data": None, "updated_at": None}


@router.put("/drafts/{form_key}")
def save_draft(form_key: str, payload: DraftSave, entity_ref: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    if len(str(payload.data)) > 200_000:
        raise HTTPException(status_code=413, detail="Draft is too large")
    row = db.query(FormDraft).filter(FormDraft.tenant_id == tenant.tenant_id, FormDraft.user_id == current_user.id, FormDraft.form_key == form_key,
                                     FormDraft.entity_ref == entity_ref).first()
    if row is None:
        row = FormDraft(tenant_id=tenant.tenant_id, user_id=current_user.id, form_key=form_key, entity_ref=entity_ref)
        db.add(row)
    row.data_json = payload.data
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"updated_at": row.updated_at.isoformat()}


@router.delete("/drafts/{form_key}", status_code=204)
def discard_draft(form_key: str, entity_ref: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    db.query(FormDraft).filter(FormDraft.tenant_id == tenant.tenant_id, FormDraft.user_id == current_user.id, FormDraft.form_key == form_key,
                               FormDraft.entity_ref == entity_ref).delete()
    db.commit()


# ---- versions ----


def _require_kind_permission(db: Session, user: User, kind: str) -> None:
    if kind not in versioning.KINDS:
        raise HTTPException(status_code=404, detail="Unknown kind")
    if not has_permission(db, require_current_tenant(), user, versioning.KINDS[kind][1]):
        raise HTTPException(status_code=403, detail=f"Missing permission: {versioning.KINDS[kind][1]}")


@router.get("/versions/{kind}/{key}")
def version_history(kind: str, key: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_kind_permission(db, current_user, kind)
    return versioning.history(db, require_current_tenant(), kind, key)


class RevertRequest(BaseModel):
    version: int


@router.post("/versions/{kind}/{key}/revert", status_code=201)
def version_revert(kind: str, key: str, payload: RevertRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_kind_permission(db, current_user, kind)
    try:
        return versioning.revert(db, require_current_tenant(), kind, key, payload.version, actor=current_user.email)
    except versioning.VersioningError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---- me: preferences + offline-readable letters/documents ----


class Preferences(BaseModel):
    reduce_motion: Optional[bool] = None
    page_size: Optional[int] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None


@router.put("/me/preferences")
def update_preferences(payload: Preferences, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.platform.settings.resolver import SettingsService

    tenant = require_current_tenant()
    service = SettingsService(db)
    mapping: dict[str, Any] = {"ux.reduce_motion": payload.reduce_motion, "ux.page_size": payload.page_size, "org.locale": payload.locale, "org.timezone": payload.timezone}
    if payload.page_size is not None and payload.page_size not in (10, 25, 50, 100):
        raise HTTPException(status_code=400, detail="page size is 10, 25, 50 or 100")
    for key, value in mapping.items():
        if value is not None:
            try:
                service.set(key, value, scope_type="user", scope_id=current_user.id, actor=current_user.email, tenant=tenant)
            except ValueError as exc:
                raise _bad(exc)
    return {"ok": True}


def _my_employee_id(db: Session, user: User):
    from app.platform.iam.org_scope import my_employee_id

    return my_employee_id(db, require_current_tenant(), user)


@router.get("/me/letters")
def my_letters(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import LetterRecord

    me = _my_employee_id(db, current_user)
    if me is None:
        return []
    rows = db.query(LetterRecord).filter(LetterRecord.tenant_id == require_current_tenant().tenant_id, LetterRecord.employee_id == me).all()
    return [{"id": str(r.id), "template_key": r.template_key, "html": r.rendered_html, "verification_token": r.verification_token} for r in rows]


@router.get("/me/documents")
def my_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.core_hr import EmployeeDocument

    me = _my_employee_id(db, current_user)
    if me is None:
        return []
    rows = db.query(EmployeeDocument).filter(EmployeeDocument.tenant_id == require_current_tenant().tenant_id, EmployeeDocument.employee_id == me,
                                             EmployeeDocument.visibility == "employee").all()
    return [{"id": str(d.id), "type": d.type, "issued_date": d.issued_date.isoformat() if d.issued_date else None,
             "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None} for d in rows]
