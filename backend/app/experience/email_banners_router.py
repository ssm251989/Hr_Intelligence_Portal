"""Part 22.6: the bundled email banners (app/platform/comms/banners/) -- public, because email clients load them.

- GET /api/v1/public/email-banners             the gallery: [{key, name, gif, png}]
- GET /api/v1/public/email-banners/{key}.gif   animated (also .png = the still fallback)
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.platform.comms.celebrate import BANNER_DIR, BANNERS

router = APIRouter(prefix="/api/v1/public/email-banners", tags=["email-banners"])


@router.get("")
def gallery():
    return [{"key": k, "name": v, "gif": f"/api/v1/public/email-banners/{k}.gif", "png": f"/api/v1/public/email-banners/{k}.png"}
            for k, v in BANNERS.items()]


@router.get("/{filename}")
def banner(filename: str):
    key, _, ext = filename.rpartition(".")
    if key not in BANNERS or ext not in ("gif", "png"):
        raise HTTPException(status_code=404, detail="No such banner")
    return FileResponse(BANNER_DIR / f"{key}.{ext}", media_type=f"image/{ext}", headers={"Cache-Control": "public, max-age=86400"})
