"""Part 15 B: company media for the friendly visual kit, and "celebrate once" markers.

- `welcome.video` -- the pre-joiner portal's welcome video/GIF (uploaded per company).
- `tour.<page>` (+ optional `tour.<page>.gif`) -- the 20-40s "Show me how" loop per page.

These are how-to/welcome clips, never personal data, so reading a file is public (a
<video src> cannot send the bearer token, and the pre-joiner portal has no staff login);
listing, uploading and removing need the settings permission.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.experience import TenantMedia, UserCelebration
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(tags=["media"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = BACKEND_ROOT / "uploads" / "media"
KEY_RE = re.compile(r"^(welcome|tour)\.[a-z0-9_-]+(\.gif)?$|^welcome\.video$|^brand\.logo$|^letters\.signature$|^email\.banner\.[a-z0-9_-]+$")  # 22.6: signatory signature, own email banners
ALLOWED_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "image/gif": "gif", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_BYTES = 50 * 1024 * 1024
# Part 17.11: the company logo (sidebar, login, careers site, emails, letters)
LOGO_KEY = "brand.logo"
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg"}
LOGO_MAX_BYTES = 2 * 1024 * 1024
STORAGE_PREFIX = "storage:"  # file_path of a file kept in the storage connection


def _storage():
    """The storage connection routed for `storage.documents`, if any (else local disk)."""
    from app.platform.connectors.registry import get_provider
    from app.platform.connectors.router import ConnectorRouter
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        resolved = ConnectorRouter(db).try_resolve("storage.documents")
        if resolved is None:
            return None
        spec = get_provider(resolved.connection.provider_code)
        if spec.adapter_cls is None or "StorageProvider" not in spec.capabilities:
            return None
        return spec.adapter_cls(resolved.connection.config_json or {}, {})
    except Exception:  # noqa: BLE001 -- storage problems fall back to local disk
        return None
    finally:
        db.close()


def _safe_svg(data: bytes) -> bytes:
    low = data.decode("utf-8", errors="ignore").lower()
    if re.search(r"<script|javascript:|<foreignobject|\son[a-z]+\s*=", low):
        raise HTTPException(status_code=400, detail="This SVG contains scripts, which aren't allowed in a logo. Please export it again as plain SVG or PNG.")
    return data


def _check_key(key: str) -> None:
    if not KEY_RE.match(key):
        raise HTTPException(status_code=400, detail="That media name isn't recognised. Use welcome.video or tour.<page>.")


def _row(m: TenantMedia) -> dict:
    return {
        "key": m.media_key, "content_type": m.content_type, "size_bytes": m.size_bytes, "title": m.title,
        "url": f"/api/v1/public/media/{m.media_key}", "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("/api/v1/media")
def list_media(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Any signed-in user may see WHICH clips exist (the "Show me how" button needs it)."""
    tenant = require_current_tenant()
    rows = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id).order_by(TenantMedia.media_key).all()
    return [_row(m) for m in rows]


@router.put("/api/v1/media/{key}")
async def upload_media(key: str, file: UploadFile = File(...), title: Optional[str] = Form(None), db: Session = Depends(get_db),
                       current_user: User = Depends(require("platform.settings.configure"))):
    _check_key(key)
    is_logo = key in (LOGO_KEY, "letters.signature")  # 22.6: the signature is an image too
    ext = (LOGO_TYPES if is_logo else ALLOWED_TYPES).get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="Please upload a PNG, JPG, WebP or SVG image." if is_logo
                            else "Please upload an MP4 or WebM video, or a GIF/PNG/JPG/WebP image.")
    data = await file.read()
    if len(data) > (LOGO_MAX_BYTES if is_logo else MAX_BYTES):
        raise HTTPException(status_code=400, detail="That logo is larger than 2 MB. Please use a smaller image." if is_logo
                            else "That file is larger than 50 MB. Please upload a shorter clip.")
    if ext == "svg":
        data = _safe_svg(data)
    tenant = require_current_tenant()
    filename = f"{uuid.uuid4()}.{ext}"
    storage = _storage()
    stored_path = None
    if storage is not None:
        from app.platform.ops.retry import is_transient, with_retry

        result = with_retry(lambda: storage.put(f"media/{tenant.tenant_id}/{filename}", data, file.content_type or "application/octet-stream"),
                            attempts=3, base_delay=0.5, retry_if=lambda r: not getattr(r, "success", True) and is_transient(getattr(r, "error", "")))
        if getattr(result, "success", False):
            stored_path = f"{STORAGE_PREFIX}media/{tenant.tenant_id}/{filename}"
    if stored_path is None:
        folder = MEDIA_DIR / str(tenant.tenant_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(data)

    row = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == key).first()
    old_path = row.file_path if row else None
    if row is None:
        row = TenantMedia(tenant_id=tenant.tenant_id, media_key=key)
        db.add(row)
    row.file_path = stored_path or f"{tenant.tenant_id}/{filename}"
    row.content_type = file.content_type
    row.size_bytes = len(data)
    row.title = title
    row.uploaded_by = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    _remove_file(old_path)
    db.refresh(row)
    return _row(row)


def _remove_file(path: Optional[str]) -> None:
    if not path:
        return
    if path.startswith(STORAGE_PREFIX):
        storage = _storage()
        if storage is not None:
            try:
                storage.delete(path[len(STORAGE_PREFIX):])
            except Exception:  # noqa: BLE001
                pass
        return
    (MEDIA_DIR / path).unlink(missing_ok=True)


@router.delete("/api/v1/media/{key}", status_code=204)
def delete_media(key: str, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    _check_key(key)
    tenant = require_current_tenant()
    row = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == key).first()
    if row is None:
        return None
    path = row.file_path
    db.delete(row)
    db.commit()
    _remove_file(path)
    return None


@router.get("/api/v1/public/media/{key}")
def media_file(key: str, db: Session = Depends(get_db)):
    _check_key(key)
    tenant = require_current_tenant()
    row = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == key).first()
    headers = {"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"}
    if row is not None and row.content_type == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    if row is not None and row.file_path.startswith(STORAGE_PREFIX):
        storage = _storage()
        try:
            data = storage.get(row.file_path[len(STORAGE_PREFIX):]) if storage is not None else None
        except Exception:  # noqa: BLE001
            data = None
        if data is None:
            raise HTTPException(status_code=404, detail="The file couldn't be read from storage.")
        from fastapi.responses import Response

        return Response(content=data, media_type=row.content_type, headers=headers)
    path = (MEDIA_DIR / row.file_path) if row else None
    if row is None or path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="No clip has been uploaded for this yet.")
    return FileResponse(path, media_type=row.content_type, headers=headers)


@router.post("/api/me/celebrations/{event_key}")
def celebrate_once(event_key: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns {"first": true} only the first time this user reaches this event."""
    if not re.fullmatch(r"[a-z0-9_.:-]{3,200}", event_key):
        raise HTTPException(status_code=400, detail="Unknown event.")
    tenant = require_current_tenant()
    exists = db.query(UserCelebration.id).filter(
        UserCelebration.tenant_id == tenant.tenant_id, UserCelebration.user_id == current_user.id, UserCelebration.event_key == event_key
    ).first()
    if exists:
        return {"first": False}
    db.add(UserCelebration(tenant_id=tenant.tenant_id, user_id=current_user.id, event_key=event_key))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"first": False}
    return {"first": True}
