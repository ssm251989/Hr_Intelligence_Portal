"""Part G: local-folder auto-import's own ready-to-upload/already-uploaded directories.

Same convention as app/candidates/storage.py's uploads/resumes and uploads/candidate-photos
-- resolved relative to the backend package location, created lazily via
mkdir(parents=True, exist_ok=True) rather than needing to exist upfront. Named and located
exactly as scoped: backend/ready_to_upload and backend/already_uploaded, deliberately NOT
nested under uploads/, and gitignored as their own .gitignore entries rather than folded
into the existing uploads/ rule.
"""

from datetime import datetime
from pathlib import Path

from app.candidates.router import ALLOWED_EXTENSIONS

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
READY_TO_UPLOAD_DIR = BACKEND_ROOT / "ready_to_upload"
ALREADY_UPLOADED_DIR = BACKEND_ROOT / "already_uploaded"


def ensure_directories() -> None:
    READY_TO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ALREADY_UPLOADED_DIR.mkdir(parents=True, exist_ok=True)


def list_ready_to_upload_files() -> list[Path]:
    """Every real resume file currently sitting in ready_to_upload/, oldest-modified first
    -- deterministic processing order. Hidden files (.gitkeep, .DS_Store, a partial-download
    marker) and anything not in ALLOWED_EXTENSIONS are never treated as resumes."""
    ensure_directories()
    files = [
        path
        for path in READY_TO_UPLOAD_DIR.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def archive_file(path: Path, outcome: str, run_started_at: datetime) -> Path:
    """Moves a processed file from ready_to_upload/ into already_uploaded/, prefixed with
    the run's timestamp and outcome (imported/duplicate/failed/no-suitable-job) so
    already_uploaded/ is self-documenting -- what happened to a given file is readable from
    its filename alone, no cross-referencing audit_log required."""
    ensure_directories()
    stamp = run_started_at.strftime("%Y%m%d-%H%M%S")
    destination = ALREADY_UPLOADED_DIR / f"{stamp}_{outcome}_{path.name}"
    path.replace(destination)
    return destination
