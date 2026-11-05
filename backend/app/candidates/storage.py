import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BACKEND_ROOT / "uploads" / "resumes"
PHOTO_UPLOAD_DIR = BACKEND_ROOT / "uploads" / "candidate-photos"


def save_resume_file(file_bytes: bytes, extension: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    (UPLOAD_DIR / filename).write_bytes(file_bytes)
    return filename


def resolve_resume_path(resume_path: str) -> Path:
    return UPLOAD_DIR / resume_path


def save_photo_file(file_bytes: bytes, extension: str) -> str:
    PHOTO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    (PHOTO_UPLOAD_DIR / filename).write_bytes(file_bytes)
    return filename


def resolve_photo_path(photo_path: str) -> Path:
    return PHOTO_UPLOAD_DIR / photo_path
