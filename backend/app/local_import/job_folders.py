"""Part G (redesign): folder-title-based job matching.

Replaces the original design's AI-guessed "Suitable For" job assignment for local-import
candidates entirely -- a resume's applied-for job is now determined deterministically by
which job-title subfolder it was dropped into, never guessed. Part B's own "Suitable For"
suggestion (app/screening/suitability.py) is untouched and still runs for every candidate
(including local-import ones, as informational metadata) -- it just no longer decides which
job the application gets created against here.
"""

import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.job_role import JobRole

# Folders are only auto-created (synced) for jobs actively soliciting candidates -- a
# draft/closed/on_hold job was never a real target to drop resumes into. Existing folders
# for jobs that later move OUT of this set are deliberately never deleted (see
# sync_job_folders) -- and are still matched against for any files already sitting there.
FOLDER_SYNC_STATUSES = ("published", "ready_for_publishing")

# Windows/macOS/Linux all forbid these in a folder name; Windows also forbids a trailing
# dot or space. Replacing rather than stripping keeps the sanitized name's word boundaries
# recognizable (e.g. "Sr. RPA Developer" -> "Sr_ RPA Developer", not "Sr RPA Developer"
# silently colliding with a genuinely different "Sr RPA Developer" job).
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_job_folder_name(title: str) -> str:
    """A job title -> a filesystem-safe folder name. Deliberately simple/lossy (this is a
    folder name, not a reversible encoding) -- collapses whitespace and strips characters
    every mainstream filesystem forbids, plus Windows' trailing dot/space rule."""
    name = _INVALID_CHARS.sub("_", title)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name or "untitled-job"


def active_jobs_for_folder_sync(db: Session) -> list[JobRole]:
    return db.query(JobRole).filter(JobRole.status.in_(FOLDER_SYNC_STATUSES)).all()


def sync_job_folders(db: Session, ready_root: Path, already_root: Path) -> dict:
    """Creates one subfolder per currently published/ready_for_publishing job under BOTH
    roots -- run at settings-save time and at the start of every scheduled scan, so a job
    published after the initial setup still gets its folders without anyone having to
    remember to re-save settings. Never deletes a folder: a job that moves to closed/on_hold
    keeps its existing folder untouched (and still scanned/matched -- see
    match_folder_to_job), since deleting it could destroy resumes a recruiter hasn't moved
    out yet.
    """
    ready_root.mkdir(parents=True, exist_ok=True)
    already_root.mkdir(parents=True, exist_ok=True)

    jobs = active_jobs_for_folder_sync(db)
    folders_created = 0
    for job in jobs:
        folder_name = sanitize_job_folder_name(job.title)
        for root in (ready_root, already_root):
            path = root / folder_name
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                folders_created += 1
    return {"jobs_considered": len(jobs), "folders_created": folders_created}


def match_folder_to_job(db: Session, folder_name: str) -> Optional[JobRole]:
    """Matches a ready-to-upload subfolder name back to exactly one job, by sanitized title,
    across every job regardless of status (a folder for a job that's since closed must
    still match -- only its *creation* is gated to published/ready_for_publishing, see
    FOLDER_SYNC_STATUSES above). Zero matches (renamed job, typo'd folder, stale folder from
    a deleted job) or more than one match (two jobs whose titles sanitize to the same name)
    both return None -- never guess which job a folder means; the caller skips and logs it
    for a human to sort out instead."""
    all_jobs = db.query(JobRole).all()
    matches = [job for job in all_jobs if sanitize_job_folder_name(job.title) == folder_name]
    if len(matches) == 1:
        return matches[0]
    return None
