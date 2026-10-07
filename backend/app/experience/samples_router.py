"""Part 22.1: Settings > Data & privacy > Sample files (the page called /api/v1/samples, which did not exist).

- GET /api/v1/samples          the sample files a company can download to try the app
- GET /api/v1/samples/{key}    one file

Files live in app/platform/samples/ (shipped with the code). The HR policy handbook is
docs/samples/CTD_Techs_Employee_Handbook_SAMPLE.pdf -- upload it in Settings > Company >
Policies & handbook and the HR assistant answers from it.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/samples", tags=["samples"])
_DIR = Path(__file__).resolve().parent.parent / "platform" / "samples"

SAMPLES = {
    "hr_policy_handbook": {
        "name": "HR policy handbook", "file": "hr_policy_handbook.pdf", "format": "pdf",
        "download_name": "CTD_Techs_Employee_Handbook_SAMPLE.pdf",
        "description": "A sample employee handbook (leave, notice period, salary dates, travel, work from home, probation). "
                       "Upload it in Settings > Company > Policies & handbook to try the HR assistant.",
    },
}


@router.get("")
def list_samples(current_user: User = Depends(get_current_user)):
    return [{"key": k, "name": v["name"], "description": v["description"], "format": v["format"]} for k, v in SAMPLES.items() if (_DIR / v["file"]).is_file()]


@router.get("/{key}")
def get_sample(key: str, current_user: User = Depends(get_current_user)):
    v = SAMPLES.get(key)
    if v is None or not (_DIR / v["file"]).is_file():
        raise HTTPException(status_code=404, detail="Sample not found")
    return FileResponse(_DIR / v["file"], filename=v["download_name"])
