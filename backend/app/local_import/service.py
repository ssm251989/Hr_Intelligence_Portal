"""Part G (redesign): local-folder auto-import, checked on a configurable interval
(local_import_settings.scan_interval_minutes, default 30 -- see app/local_import/scheduler.py).

Scans one subfolder per job under the configured ready-to-upload root (see
app/local_import/storage.py get_configured_roots), matches each subfolder back to the real
job it names (app/local_import/job_folders.match_folder_to_job -- deterministic, never
AI-guessed), and parses every matched file via one Anthropic Message Batch (cost control --
N resumes become one batch submission instead of N separate calls). Skips exact-match
duplicates (name + experience + location), and for every genuinely new candidate: creates
the Candidate record and a real Application against the folder's matched job. A subfolder
that doesn't match any real job is left completely alone (every file inside it skipped and
logged, never guessed at) -- same treatment as a genuine parse failure, both left in place
for a human to sort out rather than archived somewhere that hides the problem.

Every outcome is fully audit-logged under entity_type "local_import_run", correlated by one
run_id per scan, with per-job-folder and per-unmatched-folder breakdowns (not just a flat
total) -- see _finalize_summary.
"""

import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai_services.resume_parser import (
    ResumeParsingError,
    build_batch_request,
    extract_parsed_output_from_message,
)
from app.audit.service import log_action
from app.candidates.applications_router import create_application_record
from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError, extract_text
from app.candidates.router import parse_and_apply_resume
from app.candidates.storage import save_resume_file
from app.core.config import settings
from app.core.database import SessionLocal
from app.local_import.job_folders import match_folder_to_job, sync_job_folders
from app.local_import.storage import (
    get_configured_roots,
    list_files_in_folder,
    list_ready_to_upload_subfolders,
    move_to_already_uploaded,
)
from app.models.candidate import Candidate
from app.models.job_role import JobRole

ACTOR = "local_import_scheduler"

# Generous for what this feature is actually for -- a handful of resumes dropped in a
# folder between scheduled checks, not a bulk migration. If a batch genuinely hasn't
# finished within this window, the run reports "still processing" and leaves every matched
# file untouched (nothing moved, no candidates created) for the next run to pick back up
# from scratch -- safe to just re-submit wholesale rather than resuming a specific batch_id.
BATCH_POLL_INTERVAL_SECONDS = 5
BATCH_POLL_TIMEOUT_SECONDS = 300

# "Exact match" duplicate detection is case/whitespace-insensitive on the two text signals
# (a literal "==" would call "Jane Doe" and " jane doe " different candidates, which isn't
# what "exact match" means here) and compares experience within a tiny epsilon rather than
# raw equality purely to absorb float round-tripping through JSON storage -- not a fuzzy-
# match tolerance.
EXPERIENCE_EPSILON = 0.05

_client: Optional[Anthropic] = None


def _get_client():
    """Part 18.23-18.25: the tracked client -- model from Settings > GenAI, fallback model,
    usage counted (tokens, cost, user, module) and limits applied."""
    from app.platform.ai.tracked import tracked_client

    return tracked_client(feature="recruitment.resume_parsing", model_key="resume_extraction")


def find_duplicate_candidate(
    db: Session, full_name: Optional[str], experience_years: Optional[float], location: Optional[str]
) -> Optional[Candidate]:
    """Exact-match duplicate detection: name + experience + location, all three. Any one of
    the three signals missing means "can't determine," never "matches everything" -- so a
    resume with no extractable location, for instance, is simply never treated as a
    duplicate of anyone, rather than risking a false-positive skip."""
    if not full_name or not location or experience_years is None:
        return None
    name_norm = full_name.strip().lower()
    location_norm = location.strip().lower()
    candidates = (
        db.query(Candidate)
        .filter(
            func.lower(func.trim(Candidate.full_name)) == name_norm,
            func.lower(func.trim(Candidate.location)) == location_norm,
        )
        .all()
    )
    for existing in candidates:
        existing_experience = (existing.parsed_fields or {}).get("total_experience_years")
        if existing_experience is not None and abs(float(existing_experience) - experience_years) < EXPERIENCE_EPSILON:
            return existing
    return None


def run_local_import_scan(actor: str = ACTOR) -> dict:
    """The scheduled job's entry point (every 30 minutes -- see app/local_import/
    scheduler.py) -- also directly callable on demand (see app/local_import/router.py's
    manual-trigger endpoint, used for real functional testing without waiting for a real
    scheduled tick). Opens its own DB session since it isn't running inside a request -- no
    Depends(get_db) available from a scheduler thread."""
    db = SessionLocal()
    try:
        return _run_scan(db, actor)
    finally:
        db.close()


def _empty_summary(run_id: uuid.UUID, configured: bool) -> dict:
    return {
        "run_id": str(run_id),
        "configured": configured,
        "per_folder": {},
        "unmatched_folders": {},
        "totals": {"files_found": 0, "imported": 0, "duplicates": 0, "failed": 0, "skipped_no_matching_job": 0},
        "still_processing": 0,
        "batch_id": None,
    }


def _finalize_summary(
    run_id: uuid.UUID, per_folder: dict, unmatched_folders: dict, batch_id: Optional[str], still_processing: int
) -> dict:
    totals = {"files_found": 0, "imported": 0, "duplicates": 0, "failed": 0, "skipped_no_matching_job": 0}
    for stats in per_folder.values():
        totals["files_found"] += stats["files_found"]
        totals["imported"] += stats["imported"]
        totals["duplicates"] += stats["duplicates"]
        totals["failed"] += stats["failed"]
    for stats in unmatched_folders.values():
        totals["files_found"] += stats["files_skipped"]
        totals["skipped_no_matching_job"] += stats["files_skipped"]
    return {
        "run_id": str(run_id),
        "configured": True,
        "per_folder": per_folder,
        "unmatched_folders": unmatched_folders,
        "totals": totals,
        "still_processing": still_processing,
        "batch_id": batch_id,
    }


def _run_scan(db: Session, actor: str) -> dict:
    run_id = uuid.uuid4()

    roots = get_configured_roots(db)
    if roots is None:
        summary = _empty_summary(run_id, configured=False)
        log_action(db, "local_import_run", run_id, "local_import_run_started", actor, {"configured": False})
        log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
        return summary
    ready_root, already_root = roots

    sync_result = sync_job_folders(db, ready_root, already_root)
    log_action(
        db, "local_import_run", run_id, "local_import_run_started", actor,
        {"configured": True, **sync_result},
    )

    # Phase 1: resolve each subfolder to its job (or log+skip it, untouched) and extract
    # text locally (no AI cost) for every matched file. A subfolder with no files is never
    # even recorded -- an empty folder isn't an outcome worth a per_folder entry.
    per_folder: dict[str, dict] = {}
    unmatched_folders: dict[str, dict] = {}
    extracted: dict[str, str] = {}  # custom_id -> raw text
    context_by_custom_id: dict[str, dict] = {}  # custom_id -> {"path", "job", "folder_name"}
    custom_id_counter = 0

    for folder in list_ready_to_upload_subfolders(ready_root):
        files = list_files_in_folder(folder)
        if not files:
            continue
        folder_name = folder.name
        job = match_folder_to_job(db, folder_name)

        if job is None:
            unmatched_folders[folder_name] = {"files_skipped": 0}
            for path in files:
                log_action(
                    db, "local_import_run", run_id, "local_import_skipped_no_matching_job", actor,
                    {"filename": path.name, "folder": folder_name},
                )
                unmatched_folders[folder_name]["files_skipped"] += 1
            continue

        per_folder[folder_name] = {
            "job_id": str(job.id), "files_found": 0, "imported": 0, "duplicates": 0, "failed": 0,
        }
        for path in files:
            per_folder[folder_name]["files_found"] += 1
            try:
                raw_text = extract_text(path.read_bytes(), path.name)
            except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
                log_action(
                    db, "local_import_run", run_id, "local_import_parse_failed", actor,
                    {"filename": path.name, "folder": folder_name, "error": str(exc)},
                )
                per_folder[folder_name]["failed"] += 1
                continue
            custom_id = f"file-{custom_id_counter}"
            custom_id_counter += 1
            extracted[custom_id] = raw_text
            context_by_custom_id[custom_id] = {"path": path, "job": job, "folder_name": folder_name}

    if not extracted:
        summary = _finalize_summary(run_id, per_folder, unmatched_folders, batch_id=None, still_processing=0)
        log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
        return summary

    # Phase 2: one Batch API submission for every extracted resume, across every matched
    # folder at once -- Part G's cost control: N resumes become one request, not N.
    client = _get_client()
    batch = client.messages.batches.create(
        requests=[build_batch_request(custom_id, text) for custom_id, text in extracted.items()]
    )

    deadline = time.monotonic() + BATCH_POLL_TIMEOUT_SECONDS
    while batch.processing_status != "ended":
        if time.monotonic() >= deadline:
            log_action(
                db, "local_import_run", run_id, "local_import_run_still_processing", actor,
                {"batch_id": batch.id, "files_pending": len(extracted)},
            )
            return _finalize_summary(run_id, per_folder, unmatched_folders, batch_id=batch.id, still_processing=len(extracted))
        time.sleep(BATCH_POLL_INTERVAL_SECONDS)
        batch = client.messages.batches.retrieve(batch.id)

    outcome_key = {"imported": "imported", "duplicate": "duplicates", "failed": "failed"}
    for item in client.messages.batches.results(batch.id):
        ctx = context_by_custom_id[item.custom_id]
        outcome = _process_one_result(
            db, ctx["path"], ctx["job"], ctx["folder_name"], already_root, item, run_id, actor
        )
        per_folder[ctx["folder_name"]][outcome_key[outcome]] += 1

    summary = _finalize_summary(run_id, per_folder, unmatched_folders, batch_id=batch.id, still_processing=0)
    log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
    return summary


def _process_one_result(
    db: Session, path: Path, job: JobRole, folder_name: str, already_root: Path, item, run_id: uuid.UUID, actor: str
) -> str:
    today = date.today()

    if item.result.type != "succeeded":
        log_action(
            db, "local_import_run", run_id, "local_import_parse_failed", actor,
            {"filename": path.name, "folder": folder_name, "error": f"Batch result: {item.result.type}"},
        )
        return "failed"  # left in place -- a batch-level failure isn't fixed by moving the file

    try:
        parsed = extract_parsed_output_from_message(item.result.message)
    except ResumeParsingError as exc:
        log_action(
            db, "local_import_run", run_id, "local_import_parse_failed", actor,
            {"filename": path.name, "folder": folder_name, "error": str(exc)},
        )
        return "failed"

    duplicate = find_duplicate_candidate(
        db, parsed.get("full_name"), parsed.get("total_experience_years"), parsed.get("location")
    )
    if duplicate is not None:
        log_action(
            db, "local_import_run", run_id, "local_import_duplicate_skipped", actor,
            {
                "filename": path.name,
                "folder": folder_name,
                "matched_candidate_id": str(duplicate.id),
                "full_name": parsed.get("full_name"),
                "experience_years": parsed.get("total_experience_years"),
                "location": parsed.get("location"),
            },
        )
        move_to_already_uploaded(path, folder_name, already_root, today)
        return "duplicate"

    data = path.read_bytes()
    resume_path = save_resume_file(data, path.suffix.lower().lstrip("."))
    from app.recruitment.automation import file_hash

    candidate = Candidate(resume_path=resume_path, source="local_import", resume_sha256=file_hash(data))  # Part 17.13
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    log_action(
        db, "candidate", candidate.id, "candidate_uploaded", actor,
        {"resume_path": resume_path, "local_import_filename": path.name, "local_import_folder": folder_name},
    )

    # Applies the already-batch-parsed fields and runs the Suitable-For suggestion (Part B,
    # unaffected by this redesign -- still computed as informational metadata) -- same
    # shared logic the manual-upload and career-portal paths use, just fed a precomputed
    # result instead of parsing again. Its candidate.suitable_job_id is never read below:
    # `job` (matched by folder name, resolved before any AI call) is the real applied-for job.
    parse_and_apply_resume(db, candidate, precomputed_result=parsed, actor=actor)

    application = create_application_record(db, job, candidate, actor=actor)
    log_action(
        db, "candidate", candidate.id, "local_import_completed", actor,
        {"filename": path.name, "folder": folder_name, "application_id": str(application.id), "job_role_id": str(job.id)},
    )
    move_to_already_uploaded(path, folder_name, already_root, today)
    return "imported"
