"""Part G: hourly local-folder auto-import.

Scans backend/local_import_inbox/ for new resumes, parses them via one Anthropic Message
Batch (cost control -- N resumes become one batch submission instead of N separate calls,
at the Batch API's usual pricing discount versus the same calls made synchronously), skips
exact-match duplicates (name + experience + location), and for every genuinely new
candidate: creates the Candidate record, lets Part B's own "Suitable For" suggestion pick
the best-fitting published job, and creates the real Application against THAT job -- per
the earlier design decision that these resumes arrive with no human-chosen job to link to,
so the AI's own top pick becomes the real applied-for job, not just an informational
suggestion the way it stays for every other candidate. Every outcome (imported / duplicate /
no suitable job / failed / still-processing) is fully audit-logged under entity_type
"local_import_run", correlated by one run_id per scan.
"""

import time
import uuid
from datetime import datetime, timezone
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
from app.local_import.storage import archive_file, list_inbox_files
from app.models.candidate import Candidate
from app.models.job_role import JobRole

ACTOR = "local_import_scheduler"

# Generous for what this feature is actually for -- a handful of resumes dropped in a
# folder between hourly checks, not a bulk migration. If a batch genuinely hasn't finished
# within this window, the run reports "still processing" and leaves every file untouched in
# the inbox (nothing archived, no candidates created) for the next run to pick back up from
# scratch -- safe to just re-submit wholesale rather than resuming a specific batch_id.
BATCH_POLL_INTERVAL_SECONDS = 5
BATCH_POLL_TIMEOUT_SECONDS = 300

# "Exact match" duplicate detection is case/whitespace-insensitive on the two text signals
# (a literal "==" would call "Jane Doe" and " jane doe " different candidates, which isn't
# what "exact match" means here) and compares experience within a tiny epsilon rather than
# raw equality purely to absorb float round-tripping through JSON storage -- not a fuzzy-
# match tolerance.
EXPERIENCE_EPSILON = 0.05

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


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
    """The hourly job's entry point -- also directly callable on demand (see
    app/local_import/router.py's manual-trigger endpoint, used for real functional testing
    without waiting for a real hourly tick). Opens its own DB session since it isn't running
    inside a request -- no Depends(get_db) available from a scheduler thread."""
    db = SessionLocal()
    try:
        return _run_scan(db, actor)
    finally:
        db.close()


def _empty_summary(run_id: uuid.UUID, files_found: int, failed: int) -> dict:
    return {
        "run_id": str(run_id),
        "files_found": files_found,
        "imported": 0,
        "duplicates": 0,
        "no_suitable_job": 0,
        "failed": failed,
        "still_processing": 0,
        "batch_id": None,
    }


def _run_scan(db: Session, actor: str) -> dict:
    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    files = list_inbox_files()
    log_action(db, "local_import_run", run_id, "local_import_run_started", actor, {"files_found": len(files)})

    if not files:
        summary = _empty_summary(run_id, 0, 0)
        log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
        return summary

    # Text extraction (local, no AI cost) -- a file that can't even be read is archived
    # immediately as failed; nothing a retry next hour would fix.
    extracted: dict[str, str] = {}  # custom_id -> raw text
    file_by_custom_id: dict[str, Path] = {}
    failed = 0
    for index, path in enumerate(files):
        custom_id = f"file-{index}"
        try:
            raw_text = extract_text(path.read_bytes(), path.name)
        except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
            log_action(
                db, "local_import_run", run_id, "local_import_parse_failed", actor,
                {"filename": path.name, "error": str(exc)},
            )
            archive_file(path, "failed", started_at)
            failed += 1
            continue
        extracted[custom_id] = raw_text
        file_by_custom_id[custom_id] = path

    if not extracted:
        summary = _empty_summary(run_id, len(files), failed)
        log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
        return summary

    # One Batch API submission for every extracted resume -- Part G's cost control: N
    # resumes become one request, not N separate synchronous calls.
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
            summary = _empty_summary(run_id, len(files), failed)
            summary["still_processing"] = len(extracted)
            summary["batch_id"] = batch.id
            return summary
        time.sleep(BATCH_POLL_INTERVAL_SECONDS)
        batch = client.messages.batches.retrieve(batch.id)

    imported = 0
    duplicates = 0
    no_suitable_job = 0
    for item in client.messages.batches.results(batch.id):
        path = file_by_custom_id[item.custom_id]
        outcome = _process_one_result(db, path, item, run_id, actor)
        if outcome == "imported":
            imported += 1
        elif outcome == "duplicate":
            duplicates += 1
        elif outcome == "no_suitable_job":
            no_suitable_job += 1
        else:
            failed += 1

    summary = {
        "run_id": str(run_id),
        "files_found": len(files),
        "imported": imported,
        "duplicates": duplicates,
        "no_suitable_job": no_suitable_job,
        "failed": failed,
        "still_processing": 0,
        "batch_id": batch.id,
    }
    log_action(db, "local_import_run", run_id, "local_import_run_completed", actor, summary)
    return summary


def _process_one_result(db: Session, path: Path, item, run_id: uuid.UUID, actor: str) -> str:
    now = datetime.now(timezone.utc)

    if item.result.type != "succeeded":
        log_action(
            db, "local_import_run", run_id, "local_import_parse_failed", actor,
            {"filename": path.name, "error": f"Batch result: {item.result.type}"},
        )
        archive_file(path, "failed", now)
        return "failed"

    try:
        parsed = extract_parsed_output_from_message(item.result.message)
    except ResumeParsingError as exc:
        log_action(
            db, "local_import_run", run_id, "local_import_parse_failed", actor,
            {"filename": path.name, "error": str(exc)},
        )
        archive_file(path, "failed", now)
        return "failed"

    duplicate = find_duplicate_candidate(
        db, parsed.get("full_name"), parsed.get("total_experience_years"), parsed.get("location")
    )
    if duplicate is not None:
        log_action(
            db, "local_import_run", run_id, "local_import_duplicate_skipped", actor,
            {
                "filename": path.name,
                "matched_candidate_id": str(duplicate.id),
                "full_name": parsed.get("full_name"),
                "experience_years": parsed.get("total_experience_years"),
                "location": parsed.get("location"),
            },
        )
        archive_file(path, "duplicate", now)
        return "duplicate"

    resume_path = save_resume_file(path.read_bytes(), path.suffix.lower().lstrip("."))
    candidate = Candidate(resume_path=resume_path, source="local_import")
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    log_action(
        db, "candidate", candidate.id, "candidate_uploaded", actor,
        {"resume_path": resume_path, "local_import_filename": path.name},
    )

    # Applies the already-batch-parsed fields (including location -- see
    # app/ai_services/resume_parser.py), runs the Suitable-For suggestion (Part B), and
    # sets candidate.suitable_job_id in place -- same shared logic the manual-upload and
    # career-portal paths use, just fed a precomputed result instead of parsing again.
    parse_and_apply_resume(db, candidate, precomputed_result=parsed, actor=actor)

    if candidate.suitable_job_id:
        job = db.get(JobRole, candidate.suitable_job_id)
        application = create_application_record(db, job, candidate, actor=actor)
        log_action(
            db, "candidate", candidate.id, "local_import_completed", actor,
            {"filename": path.name, "application_id": str(application.id), "job_role_id": str(job.id)},
        )
        archive_file(path, "imported", now)
        return "imported"

    log_action(db, "candidate", candidate.id, "local_import_no_suitable_job", actor, {"filename": path.name})
    archive_file(path, "no-suitable-job", now)
    return "no_suitable_job"
