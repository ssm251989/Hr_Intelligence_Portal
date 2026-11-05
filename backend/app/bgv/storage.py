import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BACKEND_ROOT / "uploads" / "bgv"


def save_bgv_file(file_bytes: bytes, extension: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    (UPLOAD_DIR / filename).write_bytes(file_bytes)
    return filename


def resolve_bgv_path(file_path: str) -> Path:
    return UPLOAD_DIR / file_path
