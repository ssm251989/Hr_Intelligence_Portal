"""Feat 2026-10-06: actionable exit checklist (app/employees/exit_checklist.py).

Who sees an exit's checklist: HR (separation.clearance.view), the person leaving, and anyone who owns one of its items.
Who may do what is decided per item by exit_checklist.allowed() and returned as `actions`.
- GET  /api/v1/ui/exit-checklist/me                              my own exit's checklist (the person leaving)
- GET  /api/v1/ui/exit-checklist/my-tasks                        open items I own, across exits
- GET  /api/v1/ui/exit-checklist/separations/{id}                one exit's checklist
- POST /api/v1/ui/exit-checklist/items/{id}/act                  {action, data}
- POST /api/v1/ui/exit-checklist/items/{id}/upload               photo / document -> {"file": ref}
- GET  /api/v1/ui/exit-checklist/files/{tenant}/{name}           an uploaded file (same access as the checklist)
- POST /api/v1/ui/exit-checklist/separations/{id}/extend         {last_working_day}               HR
- POST /api/v1/ui/exit-checklist/separations/{id}/complete       {reason} close with items open   HR
- GET  /api/v1/ui/exit-checklist/letters/{letter_id}.pdf         relieving / experience letter PDF
Settings (platform.settings.configure): GET/PUT /api/v1/ui/exit-checklist/settings
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.employees import exit_checklist as xc
from app.models.core_hr import Employee, LetterRecord
from app.models.service_desk import CLEARANCE_OPEN, ClearanceItem, Separation
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/exit-checklist", tags=["ui-exit-checklist"])
EDIT = "separation.clearance.edit"


def _sep(db: Session, separation_id) -> Separation:
    s = db.get(Separation, separation_id)
    if s is None or s.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="That exit doesn't exist.")
    return s


def _can_see(db: Session, s: Separation, user: User) -> bool:
    tenant = require_current_tenant()
    if has_permission(db, tenant, user, "separation.clearance.view") or has_permission(db, tenant, user, EDIT):
        return True
    e = db.get(Employee, s.employee_id)
    if e is not None and e.user_id == user.id:
        return True
    return db.query(ClearanceItem).filter(ClearanceItem.separation_id == s.id, ClearanceItem.owner_user_id == user.id).first() is not None


def _visible(db: Session, separation_id, user: User) -> Separation:
    s = _sep(db, separation_id)
    if not _can_see(db, s, user):
        raise HTTPException(status_code=404, detail="That exit doesn't exist.")
    return s


def _bad(exc: Exception):
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/me")
def my_checklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    me = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == current_user.id).first()
    s = (db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == me.id)
         .order_by(Separation.created_at.desc()).first()) if me is not None else None
    if s is None or s.status in ("withdrawn", "rejected", "submitted", "retention"):
        return {"items": [], "separation_id": str(s.id) if s else None, "status": s.status if s else None}
    return xc.view(db, tenant, s, current_user)


@router.get("/my-tasks")
def my_tasks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    rows = (db.query(ClearanceItem).filter(ClearanceItem.tenant_id == tenant.tenant_id, ClearanceItem.owner_user_id == current_user.id,
                                           ClearanceItem.status.in_(CLEARANCE_OPEN)).all())
    out = []
    for i in rows:
        s = db.get(Separation, i.separation_id)
        if s is None or s.status not in ("approved", "clearance"):
            continue
        e = db.get(Employee, s.employee_id)
        out.append({**xc.item_dict(db, tenant, s, i, current_user), "separation_id": str(s.id), "employee_name": xc._name(e)})
    return {"items": sorted(out, key=lambda r: r["due_date"] or "9999")}


@router.get("/separations/{separation_id}")
def checklist(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return xc.view(db, require_current_tenant(), _visible(db, separation_id, current_user), current_user)


class ActIn(BaseModel):
    action: str
    data: dict = Field(default_factory=dict)


@router.post("/items/{item_id}/act")
def act(item_id: UUID, body: ActIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    item = db.get(ClearanceItem, item_id)
    if item is None or item.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That checklist item doesn't exist.")
    s = _visible(db, item.separation_id, current_user)
    try:
        xc.act(db, tenant, s, item, current_user, body.action, body.data or {})
    except (xc.ChecklistError, ValueError) as exc:
        raise _bad(exc) from exc
    return xc.view(db, tenant, s, current_user)


@router.post("/items/{item_id}/upload")
async def upload(item_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    item = db.get(ClearanceItem, item_id)
    if item is None or item.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="That checklist item doesn't exist.")
    _visible(db, item.separation_id, current_user)
    try:
        ref = xc.save_upload(tenant, await file.read(), file.filename or "file")
    except xc.ChecklistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"file": ref, "name": file.filename}


@router.get("/files/{tenant_id}/{name}")
def get_file(tenant_id: UUID, name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    if tenant_id != tenant.tenant_id or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="Not found.")
    ref = f"{tenant_id}/{name}"
    # the file must belong to an item of an exit this user can see
    rows = db.query(ClearanceItem).filter(ClearanceItem.tenant_id == tenant.tenant_id, cast(ClearanceItem.details_json, Text).contains(ref)).all()
    if not rows or not _can_see(db, _sep(db, rows[0].separation_id), current_user):
        raise HTTPException(status_code=404, detail="Not found.")
    path = xc.UPLOADS / str(tenant_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


class ExtendIn(BaseModel):
    last_working_day: date


@router.post("/separations/{separation_id}/extend")
def extend(separation_id: UUID, body: ExtendIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    tenant = require_current_tenant()
    s = _sep(db, separation_id)
    try:
        xc.extend(db, tenant, s, body.last_working_day, actor=current_user.email)
    except xc.ChecklistError as exc:
        raise _bad(exc) from exc
    return xc.view(db, tenant, s, current_user)


class CompleteIn(BaseModel):
    reason: Optional[str] = None


@router.post("/separations/{separation_id}/complete")
def complete(separation_id: UUID, body: CompleteIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    tenant = require_current_tenant()
    s = _sep(db, separation_id)
    reason = (body.reason or "").strip() or None
    try:
        done = xc.try_complete(db, tenant, s, actor=current_user.email, force_reason=reason)
    except xc.ChecklistError as exc:
        raise _bad(exc) from exc
    if not done:
        open_n = len(xc.pending(db, s))
        raise HTTPException(status_code=409, detail=(f"{open_n} item(s) are still open - finish them or give a reason to close anyway."
                                                     if open_n else "The exit completes after the last working day."))
    return xc.view(db, tenant, s, current_user)


@router.get("/letters/{letter_id}.pdf")
def letter_pdf(letter_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    rec = db.get(LetterRecord, letter_id)
    if rec is None or rec.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="Not found.")
    s = (db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id,
                                     (Separation.relieving_letter_id == rec.id) | (Separation.experience_letter_id == rec.id)).first())
    if s is None or not _can_see(db, s, current_user):
        raise HTTPException(status_code=404, detail="Not found.")
    return Response(xc.letter_pdf(db, rec.id), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{rec.template_key}.pdf"'})


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    return {"items": xc.config(db, require_current_tenant()), "owner_roles": list(xc.OWNER_ROLES), "auto_rules": list(xc.AUTO_RULES)}


class SettingsIn(BaseModel):
    items: list[dict]


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    try:
        return {"items": xc.save_config(db, require_current_tenant(), body.items, actor=current_user.email),
                "owner_roles": list(xc.OWNER_ROLES), "auto_rules": list(xc.AUTO_RULES)}
    except xc.ChecklistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
