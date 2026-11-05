"""Fix 2026-10-05: Settings > Company > Policies & handbook (app/copilot/policies.py).

Not under /api/v1/intelligence/copilot on purpose: that prefix is switched off with the
assistant, and HR must be able to keep its policies even while the assistant is off.

- GET    /api/v1/ui/policies                       list (+ assistant_on, ready count, categories)
- POST   /api/v1/ui/policies                       multipart: file, title, category, version?, effective_date?
- POST   /api/v1/ui/policies/{id}/new-version      multipart: file, version?, effective_date?  (replaces once Ready)
- PATCH  /api/v1/ui/policies/{id}                  title / category / version / effective_date
- POST   /api/v1/ui/policies/{id}/retry            process a Failed file again
- DELETE /api/v1/ui/policies/{id}
- GET    /api/v1/ui/policies/{id}/file             the original file (preview / download)
- GET    /api/v1/ui/policies/{id}/text             the text the assistant reads (preview)
- GET    /api/v1/ui/policies/sample                a sample handbook (.docx)
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.copilot import policies
from app.core.database import get_db
from app.models.intelligence import KnowledgeChunk, KnowledgeDocument
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/policies", tags=["ui-policies"])
VIEW, CONFIGURE = "copilot.knowledge.view", "copilot.knowledge.configure"


def _get(db: Session, document_id: UUID) -> KnowledgeDocument:
    tenant = require_current_tenant()
    row = db.get(KnowledgeDocument, document_id)
    if row is None or row.tenant_id != tenant.tenant_id or row.status == "deleted":
        raise HTTPException(status_code=404, detail="That policy no longer exists.")
    return row


def _date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="The effective date isn't a valid date.")


def _assistant_on(db: Session) -> bool:
    from app.platform.ai.governance import feature_enabled
    from app.platform.modules import enabled_modules

    tenant = require_current_tenant()
    return "copilot" in enabled_modules(db, tenant) and bool(feature_enabled(db, tenant, "copilot.chat"))


@router.get("")
def list_policies(db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    tenant = require_current_tenant()
    policies.resume_stuck(db, tenant)
    return {"policies": policies.listing(db, tenant), "ready": policies.ready_count(db, tenant), "assistant_on": _assistant_on(db),
            "categories": list(policies.CATEGORIES), "max_mb": policies.MAX_BYTES // (1024 * 1024)}


@router.get("/sample")
def sample(current_user: User = Depends(require(VIEW))):
    return Response(policies.sample_docx(), media_type=policies.TYPES["docx"],
                    headers={"Content-Disposition": 'attachment; filename="sample-employee-handbook.docx"'})


@router.post("", status_code=201)
async def upload_policy(background: BackgroundTasks, file: UploadFile = File(...), title: str = Form(""), category: str = Form("other"),
                        version: Optional[str] = Form(None), effective_date: Optional[str] = Form(None),
                        db: Session = Depends(get_db), current_user: User = Depends(require(CONFIGURE))):
    tenant = require_current_tenant()
    try:
        row = policies.upload(db, tenant, data=await file.read(), filename=file.filename or "", title=title, category=category,
                              version=version, effective_date=_date(effective_date), actor=current_user.email)
    except policies.PolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    background.add_task(policies.process_later, tenant, row.id)
    return policies.to_dict(row)


@router.post("/{document_id}/new-version", status_code=201)
async def new_version(document_id: UUID, background: BackgroundTasks, file: UploadFile = File(...), version: Optional[str] = Form(None),
                      effective_date: Optional[str] = Form(None), db: Session = Depends(get_db), current_user: User = Depends(require(CONFIGURE))):
    tenant = require_current_tenant()
    old = _get(db, document_id)
    if old.status == "processing":
        raise HTTPException(status_code=409, detail="This file is still being read. Wait until it is Ready or Failed, then upload the new version.")
    try:
        row = policies.upload(db, tenant, data=await file.read(), filename=file.filename or "", title=old.title, category=old.category or "other",
                              version=version, effective_date=_date(effective_date), actor=current_user.email, replaces=old)
    except policies.PolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if old.status == "failed":  # a failed upload has nothing to keep answering with -- replace it outright
        row.replaces_id = old.replaces_id  # the Ready version before it (if any) is still the one to replace
        old.replaces_id = None
        policies.delete(db, tenant, old, actor=current_user.email)
        db.commit()
    background.add_task(policies.process_later, tenant, row.id)
    return policies.to_dict(row)


class DetailsIn(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    version: Optional[str] = None
    effective_date: Optional[str] = None


@router.patch("/{document_id}")
def edit_details(document_id: UUID, body: DetailsIn, db: Session = Depends(get_db), current_user: User = Depends(require(CONFIGURE))):
    row = policies.update_details(db, require_current_tenant(), _get(db, document_id), title=body.title, category=body.category,
                                  version=body.version, effective_date=_date(body.effective_date), actor=current_user.email)
    return policies.to_dict(row)


@router.post("/{document_id}/retry")
def retry(document_id: UUID, background: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(require(CONFIGURE))):
    row = _get(db, document_id)
    if row.status != "failed" or not row.file_path:
        raise HTTPException(status_code=409, detail="Only a Failed file can be tried again.")
    row.status, row.error = "processing", None
    db.commit()
    background.add_task(policies.process_later, require_current_tenant(), row.id)
    return policies.to_dict(row)


@router.delete("/{document_id}", status_code=204)
def delete_policy(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(CONFIGURE))):
    policies.delete(db, require_current_tenant(), _get(db, document_id), actor=current_user.email)
    return Response(status_code=204)


@router.get("/{document_id}/file")
def policy_file(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    tenant = require_current_tenant()
    row = db.get(KnowledgeDocument, document_id)
    if row is None or row.tenant_id != tenant.tenant_id or not row.file_path:
        raise HTTPException(status_code=404, detail="The file for this policy isn't available.")
    try:
        data = policies.read_file(row.file_path)
    except (OSError, policies.PolicyError):
        raise HTTPException(status_code=404, detail="The file for this policy couldn't be found in storage.")
    name = (row.file_name or "policy").replace('"', "")
    return Response(data, media_type=row.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/{document_id}/text")
def policy_text(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require(VIEW))):
    row = _get(db, document_id)
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == row.id).order_by(KnowledgeChunk.ordinal).all()
    return {"id": str(row.id), "title": row.title, "status": policies.to_dict(row)["status"],
            "passages": [{"heading": c.heading, "text": c.body} for c in chunks]}
