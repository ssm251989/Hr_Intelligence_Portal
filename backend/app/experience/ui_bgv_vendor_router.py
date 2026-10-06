"""Part 21.4: BGV Download all + BGV vendors (app/bgv/vendors.py).

HR (recruitment.bgv.view / .edit):
- GET  /api/v1/ui/bgv/vendors                               active BGV vendors (agencies of type BGV / Both) with their checks
- GET  /api/v1/ui/bgv/{application_id}/assignments          this candidate's vendor assignments (current first)
- POST /api/v1/ui/bgv/{application_id}/assign               {agency_id, checks, due_date}  (reassigns if one is open)
- POST /api/v1/ui/bgv/assignments/{id}/cancel               {reason}
- GET  /api/v1/ui/bgv/assignments/{id}/report               the vendor's report file
- GET  /api/v1/ui/bgv/{application_id}/download-all         ZIP of all this candidate's BGV documents + summary Excel
- POST /api/v1/ui/bgv/download-all                          {application_ids}: ZIP, or {export_id} prepared in the background
- GET  /api/v1/ui/bgv/exports/{export_id}                   a background ZIP when ready
Vendor (public, the secure link):
- GET  /api/v1/public/bgv-vendor/{token}                    candidate, checks, due date, documents (opening it = In progress)
- GET  /api/v1/public/bgv-vendor/{token}/files/{doc_id}     one document
- POST /api/v1/public/bgv-vendor/{token}/report             upload the report (+ note)
"""

import uuid
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.bgv import vendors as v
from app.core.database import get_db
from app.models.agency import BgvAssignment
from app.models.application import Application
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/bgv", tags=["ui-bgv-vendor"])
public_router = APIRouter(prefix="/api/v1/public/bgv-vendor", tags=["public-bgv-vendor"])
VIEW, EDIT = "recruitment.bgv.view", "recruitment.bgv.edit"


def _app(db: Session, application_id) -> Application:
    a = db.get(Application, application_id)
    if a is None or a.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


def _assignment(db: Session, assignment_id) -> BgvAssignment:
    a = db.get(BgvAssignment, assignment_id)
    if a is None or a.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="Not found")
    return a


def _zip_response(data: bytes, name: str) -> Response:
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/vendors")
def list_vendors(db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    return {"items": v.vendors(db, require_current_tenant())}


@router.post("/download-all")
def download_all_bulk(body: dict, background: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    ids = [UUID(str(x)) for x in (body.get("application_ids") or [])][:500]
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one candidate.")
    tenant = require_current_tenant()
    apps = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.id.in_(ids)).all()
    if len(apps) > v.BULK_INLINE:
        export_id = uuid.uuid4().hex[:16]
        background.add_task(v.bulk_export, tenant.tenant_id, export_id, [a.id for a in apps], current_user.email)
        log_action(db, "bgv_export", None, "bgv_download_all_started", current_user.email[:50], {"export_id": export_id, "candidates": len(apps)})
        return {"export_id": export_id, "candidates": len(apps), "background": True}
    data, counts = v.build_zip(db, apps)
    log_action(db, "bgv_export", None, "bgv_download_all", current_user.email[:50], {"application_ids": [str(a.id) for a in apps], **counts})
    return _zip_response(data, f"bgv-documents-{len(apps)}-candidates.zip")


@router.get("/exports/{export_id}")
def get_export(export_id: str, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    p = v.export_path(require_current_tenant(), export_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Still being prepared - try again in a minute.")
    return FileResponse(p, filename=f"bgv-documents-{export_id}.zip", media_type="application/zip")


@router.get("/assignments/{assignment_id}/report")
def get_report(assignment_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    a = _assignment(db, assignment_id)
    p = v.report_file(a)
    if p is None:
        raise HTTPException(status_code=404, detail="No report yet")
    return FileResponse(p, filename=a.report_name or p.name)


class CancelIn(BaseModel):
    reason: Optional[str] = None


@router.post("/assignments/{assignment_id}/cancel")
def cancel_assignment(assignment_id: UUID, body: CancelIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    try:
        return v.cancel(db, require_current_tenant(), _assignment(db, assignment_id), actor=current_user.email, reason=body.reason)
    except v.VendorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{application_id}/download-all")
def download_all(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    app = _app(db, application_id)
    data, counts = v.build_zip(db, [app])
    name, _job = v._names(db, app)
    log_action(db, "application", app.id, "bgv_download_all", current_user.email[:50], counts)
    return _zip_response(data, f"{v._safe(name)} - BGV documents.zip")


@router.get("/{application_id}/assignments")
def list_assignments(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    app = _app(db, application_id)
    rows = db.query(BgvAssignment).filter(BgvAssignment.application_id == app.id).order_by(BgvAssignment.created_at.desc()).all()
    return {"items": [v.assignment_dict(db, a, with_link=True) for a in rows], "status": app.status}


class AssignIn(BaseModel):
    agency_id: UUID
    checks: list[str] = Field(default_factory=list)
    due_date: Optional[date] = None


@router.post("/{application_id}/assign")
def assign_vendor(application_id: UUID, body: AssignIn, db: Session = Depends(get_db), current_user: User = Depends(require(EDIT))):
    try:
        return v.assign(db, require_current_tenant(), _app(db, application_id), agency_id=body.agency_id, checks=body.checks,
                        due_date=body.due_date, actor=current_user.email)
    except v.VendorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---- the vendor's secure link ----


def _resolve(db: Session, token: str) -> BgvAssignment:
    try:
        a = v.resolve(db, token)
    except v.VendorError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    if a.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="Not found")
    return a


@public_router.get("/{token}")
def vendor_page(token: str, db: Session = Depends(get_db)):
    return v.vendor_view(db, require_current_tenant(), _resolve(db, token))


@public_router.get("/{token}/files/{doc_id}")
def vendor_file(token: str, doc_id: str, db: Session = Depends(get_db)):
    try:
        path, name = v.vendor_file(db, _resolve(db, token), doc_id)
    except v.VendorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=name)


@public_router.post("/{token}/report")
async def vendor_report(token: str, file: UploadFile = File(...), note: Optional[str] = Form(None), db: Session = Depends(get_db)):
    a = _resolve(db, token)
    try:
        return v.upload_report(db, require_current_tenant(), a, await file.read(), file.filename or "report.pdf", note)
    except v.VendorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
