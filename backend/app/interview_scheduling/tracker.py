"""Interview Scheduling automation's Excel tracker -- a workbook the recruiter owns and can
open/edit directly, with three sheets:

  "Interviewer Pool": Job Title | Eligible Interviewers (comma-separated names)
  "Interview Log": Candidate | Job Title | Assigned Interviewer | Candidate Preferred Time |
                   Interviewer Confirmed | Candidate Confirmed | Final Scheduled Time |
                   Status | Slots Offered | Candidate Selected Slot | Confirmation Link Token
  "Mails": Name | Mail Id -- interviewer full_name -> the address the interviewer-first
           negotiation flow (app/interview_scheduling/negotiation.py) emails slot offers to.

Each row starts out written by service.py's select_interviewer with "Interviewer
Confirmed"/"Candidate Confirmed"/"Final Scheduled Time" blank and Status "Interviewer
Selected -- Awaiting Confirmation" -- that's as far as the foundation stage goes. Part 3
(app/interview_scheduling/confirmation.py) fills those three columns in and finalizes
Status once the candidate actually confirms a slot via their emailed link, using
update_interview_log_row below. An earlier plan to do that confirmation over WhatsApp/
Twilio was dropped before any of it was built, in favor of email + a secure single-use link,
which this app already had a real Gmail integration for.

"Slots Offered"/"Candidate Selected Slot"/"Confirmation Link Token" and the "Mails" sheet
are the interviewer-first negotiation flow's own columns/sheet -- negotiation.py writes and
reads them; the older select_interviewer/confirmation.py flow above never touches them.
"""

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from app.integrations.google_calendar import APP_TIMEZONE
from app.local_import.job_folders import FOLDER_SYNC_STATUSES
from app.models.job_role import JobRole

# Part 1 pending-fix baseline (docs/HRMS_COMPLETE_SPEC.txt): moves into the Settings
# Registry as recruitment.tracker.save_retry.attempts / .backoff_seconds once Part 2 exists.
_SAVE_RETRY_ATTEMPTS = 5
_SAVE_RETRY_BACKOFF_SECONDS = 0.5


class TrackerFileLockedError(Exception):
    """The tracker workbook could not be saved -- it's open for editing elsewhere (Excel
    holds an OS-level write lock on Windows while a file is open in it) and stayed locked
    through every retry. Callers must surface this as a clear, retryable "close the file"
    message, never a raw 500."""


def _save_with_retry(
    workbook: Workbook,
    path: Path,
    attempts: int = _SAVE_RETRY_ATTEMPTS,
    backoff_s: float = _SAVE_RETRY_BACKOFF_SECONDS,
) -> None:
    """Every write path in this module goes through this instead of calling
    workbook.save(path) directly, retrying on PermissionError (the recruiter has the
    tracker open in Excel) up to `attempts` times with a `backoff_s` pause between tries
    before giving up with TrackerFileLockedError -- a transient "I had it open for a second"
    now resolves itself instead of failing the caller's whole action outright."""
    last_error: Optional[PermissionError] = None
    for attempt in range(attempts):
        try:
            workbook.save(path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(backoff_s)
    raise TrackerFileLockedError(
        f"Tracker file is open in Excel -- close it and retry. ({path})"
    ) from last_error


INTERVIEWER_POOL_SHEET = "Interviewer Pool"
INTERVIEWER_POOL_COLUMNS = ["Job Title", "Eligible Interviewers"]

INTERVIEW_LOG_SHEET = "Interview Log"
INTERVIEW_LOG_COLUMNS = [
    "Candidate", "Job Title", "Assigned Interviewer", "Candidate Preferred Time",
    "Interviewer Confirmed", "Candidate Confirmed", "Final Scheduled Time", "Status",
    "Slots Offered", "Candidate Selected Slot", "Confirmation Link Token",
]

MAILS_SHEET = "Mails"
MAILS_COLUMNS = ["Name", "Mail Id"]

_SHEET_SPECS = (
    (INTERVIEWER_POOL_SHEET, INTERVIEWER_POOL_COLUMNS),
    (INTERVIEW_LOG_SHEET, INTERVIEW_LOG_COLUMNS),
    (MAILS_SHEET, MAILS_COLUMNS),
)

# Interview Log Status values that represent a genuinely negative/declined outcome -- a row
# with one of these never counts as evidence an interviewer is "busy," since nothing was
# actually booked for them.
_NON_BUSY_STATUSES = {
    "no interviewer available", "not available", "slot not selected by candidate",
    "manual scheduling required",
}


def ensure_tracker_file(path: Path) -> dict:
    """Creates the tracker workbook with both sheets/headers if `path` doesn't exist yet.

    If it already exists, this NEVER overwrites it or touches existing rows -- it only adds
    whatever sheets/columns are missing (a missing sheet gets created with its header row; an
    existing sheet missing some expected columns gets those columns appended to the END of
    its header row, never reordering or replacing what's already there). Returns a summary of
    what was actually done, for the Settings page to show the recruiter.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        # Workbook() starts with one default sheet ("Sheet") -- drop it once the two real
        # sheets exist, rather than leaving a stray empty sheet in every fresh tracker.
        default_sheet = workbook.active
        for sheet_name, columns in _SHEET_SPECS:
            sheet = workbook.create_sheet(sheet_name)
            sheet.append(columns)
        workbook.remove(default_sheet)
        _save_with_retry(workbook, path)
        return {
            "created": True,
            "sheets_added": [name for name, _ in _SHEET_SPECS],
            "columns_added": {name: list(columns) for name, columns in _SHEET_SPECS},
        }

    workbook = load_workbook(path)
    sheets_added: list[str] = []
    columns_added: dict[str, list[str]] = {}

    for sheet_name, expected_columns in _SHEET_SPECS:
        if sheet_name not in workbook.sheetnames:
            sheet = workbook.create_sheet(sheet_name)
            sheet.append(expected_columns)
            sheets_added.append(sheet_name)
            columns_added[sheet_name] = list(expected_columns)
            continue

        sheet = workbook[sheet_name]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
        existing_header = [cell.value for cell in header_row if cell.value is not None]
        if not existing_header:
            # A sheet that exists but has no header yet (e.g. a blank sheet someone
            # pre-created by hand) -- write the real header fresh, no data to preserve.
            sheet.append(expected_columns)
            columns_added[sheet_name] = list(expected_columns)
            continue

        missing = [col for col in expected_columns if col not in existing_header]
        if missing:
            start_col = sheet.max_column + 1
            for offset, col in enumerate(missing):
                sheet.cell(row=1, column=start_col + offset, value=col)
            columns_added[sheet_name] = missing

    if sheets_added or columns_added:
        _save_with_retry(workbook, path)

    return {"created": False, "sheets_added": sheets_added, "columns_added": columns_added}


def read_mail_directory(path: Path) -> dict[str, str]:
    """Interviewer full_name (lowercased/whitespace-stripped) -> the email address the
    interviewer-first negotiation flow (app/interview_scheduling/negotiation.py) sends slot
    offers to, from the tracker's "Mails" sheet. Deliberately separate from a registered
    User's own `email` column -- an Interviewer Pool name might not even resolve to a
    registered account (negotiation.py checks that independently, for the later
    calendar-event step), and this sheet is the recruiter's own record of where to actually
    reach that person. Empty dict if the sheet or its expected columns aren't present --
    same "nothing configured yet, not an error" convention as read_interviewer_pool."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if MAILS_SHEET not in workbook.sheetnames:
            return {}
        sheet = workbook[MAILS_SHEET]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
        header = [cell.value for cell in header_row]
        if "Name" not in header or "Mail Id" not in header:
            return {}
        name_col = header.index("Name")
        mail_col = header.index("Mail Id")

        directory: dict[str, str] = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row is None or len(row) <= max(name_col, mail_col):
                continue
            name, mail = row[name_col], row[mail_col]
            if not name or not mail:
                continue
            directory[str(name).strip().lower()] = str(mail).strip()
        return directory
    finally:
        # read_only=True keeps a live handle on the underlying zip archive for lazy
        # iteration -- unlike the normal (non-read-only) load below, which reads
        # everything into memory up front and releases the OS file handle immediately.
        # Without this close(), the handle only goes away whenever CPython's cyclic GC
        # (not simple refcounting, since openpyxl's internal objects hold reference
        # cycles) gets around to collecting it -- an indeterminate delay during which
        # this file is genuinely locked at the OS level (confirmed: even a plain
        # os.rename() on it fails with WinError 32 until this runs). That's the real
        # cause of the "sharing violation opening this file in Excel" report -- the
        # tracker is meant to be human-editable at any time.
        workbook.close()


def email_for_interviewer(path: Path, interviewer_name: str) -> Optional[str]:
    """The one email address the Mails sheet has for this interviewer name (case/
    whitespace-insensitive), or None if it isn't listed there at all."""
    return read_mail_directory(path).get(interviewer_name.strip().lower())


def _parse_ist_datetime(value: object) -> Optional[datetime]:
    """Reverse of app.integrations.google_calendar.format_ist_datetime -- the exact string
    format every date/time column in this tracker is written in (e.g.
    "26 Aug 2026, 10:00 AM IST"). None for a blank cell or anything that doesn't parse (a
    hand-edited cell in some other format) -- an unreadable date is simply never counted as
    evidence of anything, not an error."""
    if not value:
        return None
    text_value = str(value).strip()
    if text_value.upper().endswith(" IST"):
        text_value = text_value[: -len(" IST")].strip()
    try:
        naive = datetime.strptime(text_value, "%d %b %Y, %I:%M %p")
    except ValueError:
        return None
    return naive.replace(tzinfo=APP_TIMEZONE)


def _current_week_bounds_ist(now: datetime) -> tuple[date, date]:
    today = now.astimezone(APP_TIMEZONE).date()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def interviewer_busy_this_week(path: Path, interviewer_name: str, now: Optional[datetime] = None) -> bool:
    """True if the Interview Log sheet already shows a real (non-declined) commitment for
    this interviewer sometime in the current Monday-Sunday IST week. The ONLY busy-check
    source for the interviewer-first negotiation flow (app/interview_scheduling/
    negotiation.py) -- deliberately a week-level heuristic read straight off the recruiter's
    own tracker, not an exact-slot real-time Calendar conflict check the way the older
    service.py select_interviewer flow works.

    Prefers "Final Scheduled Time" (a confirmed interview actually landed on a date) and
    falls back to "Candidate Preferred Time" (a still-pending proposal) when a row has no
    Final Scheduled Time yet -- either way, a row only counts when its Status isn't one of
    _NON_BUSY_STATUSES (a genuinely negative/declined outcome, where nothing was actually
    booked for that interviewer).
    """
    now = now or datetime.now(APP_TIMEZONE)
    week_start, week_end = _current_week_bounds_ist(now)
    target = interviewer_name.strip().lower()

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if INTERVIEW_LOG_SHEET not in workbook.sheetnames:
            return False
        sheet = workbook[INTERVIEW_LOG_SHEET]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
        header = [cell.value for cell in header_row if cell.value is not None]
        if "Assigned Interviewer" not in header or "Status" not in header:
            return False
        col = {name: header.index(name) for name in header}
        final_col = col.get("Final Scheduled Time")
        preferred_col = col.get("Candidate Preferred Time")

        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row is None or len(row) < len(header):
                continue
            assigned = row[col["Assigned Interviewer"]]
            if not assigned or str(assigned).strip().lower() != target:
                continue
            status = str(row[col["Status"]] or "").strip().lower()
            if status in _NON_BUSY_STATUSES:
                continue
            when = _parse_ist_datetime(row[final_col]) if final_col is not None else None
            if when is None and preferred_col is not None:
                when = _parse_ist_datetime(row[preferred_col])
            if when is None:
                continue
            if week_start <= when.date() <= week_end:
                return True
        return False
    finally:
        # See read_mail_directory's own comment on why read_only mode needs an explicit
        # close() rather than relying on GC.
        workbook.close()


def read_interviewer_pool(path: Path) -> dict[str, list[str]]:
    """Job title -> the list of eligible interviewer names configured for it (parsed from
    the comma-separated "Eligible Interviewers" column) -- whitespace around each name is
    stripped, empty entries (a trailing comma, a wholly blank cell) are dropped, and a name
    repeated in the same cell (case/whitespace-insensitive) is kept only once, at its FIRST
    position, so a recruiter accidentally listing someone twice doesn't double their odds of
    being picked or double-count them in interviewer-load reporting. A ";" is NOT a
    recognized separator (only "," is, per the column's own header) -- a cell like "A;B" is
    one literal interviewer name, not two. Empty dict if the sheet or its expected columns
    aren't present -- callers treat that as "nothing configured yet", not an error."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if INTERVIEWER_POOL_SHEET not in workbook.sheetnames:
            return {}
        sheet = workbook[INTERVIEWER_POOL_SHEET]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
        header = [cell.value for cell in header_row]
        if "Job Title" not in header or "Eligible Interviewers" not in header:
            return {}
        job_col = header.index("Job Title")
        interviewers_col = header.index("Eligible Interviewers")

        pool: dict[str, list[str]] = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row is None or len(row) <= max(job_col, interviewers_col):
                continue
            job_title = row[job_col]
            if not job_title:
                continue
            interviewers_raw = row[interviewers_col] or ""
            names: list[str] = []
            seen: set[str] = set()
            for raw_name in str(interviewers_raw).split(","):
                name = raw_name.strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)
            pool[str(job_title).strip()] = names
        return pool
    finally:
        # See read_mail_directory's own comment on why read_only mode needs an explicit
        # close() rather than relying on GC.
        workbook.close()


def eligible_interviewers_for_job(path: Path, job_title: str) -> list[str]:
    """The eligible interviewer names for one job title -- case/whitespace-normalized
    matching (not fuzzy) against the pool's own Job Title column, since recruiters typing
    the same title into two different systems rarely match byte-for-byte."""
    target = job_title.strip().lower()
    for title, names in read_interviewer_pool(path).items():
        if title.lower() == target:
            return names
    return []


def sync_interviewer_pool_job_titles(db: Session, path: Path) -> dict:
    """Adds one Interviewer Pool row -- Job Title filled in, "Eligible Interviewers" left
    blank -- for every currently published/ready_for_publishing job whose title isn't
    already in the sheet (case/whitespace-insensitive match, same as
    eligible_interviewers_for_job). Same sync principle as app/local_import/job_folders.py's
    sync_job_folders, reusing its FOLDER_SYNC_STATUSES: never overwrites an existing row's
    "Eligible Interviewers" list, and never removes a row for a job that later moves out of
    that status set (e.g. closes) -- that row may already hold a recruiter's real interviewer
    list, or a job that later closes may still have an interview in flight, so it's left for
    manual cleanup rather than silently disappearing.
    """
    ensure_tracker_file(path)
    existing_titles = {title.strip().lower() for title in read_interviewer_pool(path)}
    jobs = db.query(JobRole).filter(JobRole.status.in_(FOLDER_SYNC_STATUSES)).all()

    titles_to_add: list[str] = []
    seen: set[str] = set()
    for job in jobs:
        key = job.title.strip().lower()
        if key in existing_titles or key in seen:
            continue
        seen.add(key)
        titles_to_add.append(job.title)

    if not titles_to_add:
        return {"jobs_considered": len(jobs), "rows_added": 0}

    workbook = load_workbook(path)
    sheet = workbook[INTERVIEWER_POOL_SHEET]
    header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
    header = [cell.value for cell in header_row if cell.value is not None]
    for title in titles_to_add:
        sheet.append([title if col == "Job Title" else "" for col in header])
    _save_with_retry(workbook, path)
    return {"jobs_considered": len(jobs), "rows_added": len(titles_to_add)}


def append_interview_log_row(path: Path, values: dict[str, Optional[str]]) -> None:
    """Appends one new row to the Interview Log sheet -- never edits or removes existing
    rows. Any column in INTERVIEW_LOG_COLUMNS not present in `values` is left blank (e.g.
    Interviewer Confirmed/Candidate Confirmed/Final Scheduled Time, which this foundation
    stage never fills in -- that's Stage 2's job once WhatsApp confirmations exist)."""
    workbook = load_workbook(path)
    sheet = workbook[INTERVIEW_LOG_SHEET] if INTERVIEW_LOG_SHEET in workbook.sheetnames else workbook.create_sheet(INTERVIEW_LOG_SHEET)
    header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
    header = [cell.value for cell in header_row if cell.value is not None]
    if not header:
        sheet.append(INTERVIEW_LOG_COLUMNS)
        header = list(INTERVIEW_LOG_COLUMNS)
    sheet.append([values.get(column, "") or "" for column in header])
    _save_with_retry(workbook, path)


def update_interview_log_row(
    path: Path, *, candidate: str, job_title: str, preferred_time: str, updates: dict[str, str]
) -> bool:
    """Finds the Interview Log row a prior append_interview_log_row call wrote for this
    exact (Candidate, Job Title, Candidate Preferred Time) -- there's no row id to key off
    of, but those three together are what a proposed slot is uniquely identified by -- and
    applies `updates` to just that row's named columns, in place. If more than one row
    somehow matches, the last one (most recently appended) wins. Never appends a new row and
    never touches any other row or column.

    Returns False as a deliberate no-op, never an exception, if no matching row is found
    (e.g. the tracker file was replaced after the row was originally logged) or the expected
    columns aren't present -- a stale/missing tracker row shouldn't block whatever real
    action (e.g. a candidate's interview confirmation) triggered this update.
    """
    workbook = load_workbook(path)
    if INTERVIEW_LOG_SHEET not in workbook.sheetnames:
        return False
    sheet = workbook[INTERVIEW_LOG_SHEET]
    header_row = next(sheet.iter_rows(min_row=1, max_row=1), ())
    header = [cell.value for cell in header_row if cell.value is not None]
    if not header:
        return False
    col_index = {name: i for i, name in enumerate(header)}
    match_columns = {"Candidate": candidate, "Job Title": job_title, "Candidate Preferred Time": preferred_time}
    if any(col not in col_index for col in match_columns):
        return False

    target_row = None
    for row in sheet.iter_rows(min_row=2):
        if all(
            len(row) > col_index[col] and str(row[col_index[col]].value or "") == expected
            for col, expected in match_columns.items()
        ):
            target_row = row  # keep scanning -- last match wins if duplicates somehow exist

    if target_row is None:
        return False

    for column_name, value in updates.items():
        if column_name in col_index:
            target_row[col_index[column_name]].value = value
    _save_with_retry(workbook, path)
    return True
