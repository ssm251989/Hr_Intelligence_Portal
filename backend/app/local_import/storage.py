"""Part G (redesign): local-folder auto-import's configurable root directories.

Unlike the original design's fixed backend/ready_to_upload and backend/already_uploaded
folders, both roots are now absolute paths on the server machine, configured once via the
"Import from Source" wizard's Local Import configure step and stored in
local_import_settings (see app/models/local_import_settings.py). Each root contains one
subfolder per job (see app/local_import/job_folders.py) rather than a single flat folder.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.candidates.router import ALLOWED_EXTENSIONS
from app.models.local_import_settings import LocalImportSettings


def get_local_import_settings(db: Session) -> LocalImportSettings:
    """The singleton settings row (id=1), seeded by migration c8a1f4d7e6b2. Defensively
    creates it if somehow missing (e.g. a test DB that ran migrations before this table
    existed) rather than crashing the scan outright."""
    settings_row = db.get(LocalImportSettings, 1)
    if settings_row is None:
        settings_row = LocalImportSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def get_configured_roots(db: Session) -> Optional[tuple[Path, Path]]:
    """None until a recruiter has saved both paths via the wizard -- callers (the scheduled
    scan, the manual-trigger endpoint) must treat that as "nothing to do yet", not an
    error."""
    settings_row = get_local_import_settings(db)
    if not settings_row.ready_to_upload_root or not settings_row.already_uploaded_root:
        return None
    return Path(settings_row.ready_to_upload_root), Path(settings_row.already_uploaded_root)


def list_ready_to_upload_subfolders(ready_root: Path) -> list[Path]:
    """Every real subfolder currently under the ready-to-upload root -- not filtered by
    which jobs are currently published, since a folder for a job that's since closed must
    still be scanned (see job_folders.match_folder_to_job). Hidden directories are skipped."""
    if not ready_root.exists():
        return []
    return sorted(
        path for path in ready_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def list_files_in_folder(folder: Path) -> list[Path]:
    """Every real resume file directly inside one job subfolder, oldest-modified first --
    deterministic processing order. Hidden files and anything not in ALLOWED_EXTENSIONS are
    never treated as resumes."""
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def move_to_already_uploaded(path: Path, folder_name: str, already_root: Path, as_of: date) -> Path:
    """Moves a successfully-processed (imported or duplicate) file into the SAME-NAMED
    subfolder under the already-uploaded root, renamed to "{original filename}_{YYYY-MM-DD}
    {extension}" so a resubmission of the same filename later never collides with this one.
    Creates the destination subfolder defensively if it somehow doesn't exist yet (sync
    should have already created it, but a file sitting in a folder sync hasn't run against
    yet must still be movable)."""
    destination_dir = already_root / folder_name
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{path.stem}_{as_of.strftime('%Y-%m-%d')}{path.suffix}"
    path.replace(destination)
    return destination
