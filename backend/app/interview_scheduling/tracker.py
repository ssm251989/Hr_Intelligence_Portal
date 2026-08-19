"""Interview Scheduling automation's Excel tracker (foundation stage) -- a workbook the
recruiter owns and can open/edit directly, with two sheets:

  "Interviewer Pool": Job Title | Eligible Interviewers (comma-separated names)
  "Interview Log": Candidate | Job Title | Assigned Interviewer | Candidate Preferred Time |
                   Interviewer Confirmed | Candidate Confirmed | Final Scheduled Time | Status

"Interviewer Confirmed"/"Candidate Confirmed"/"Final Scheduled Time" are written by this
stage's caller as blank -- they're Stage 2's concern (the WhatsApp confirmation flow), once
real Twilio credentials are available. This stage only ever selects a candidate interviewer
and records that selection; it never creates a real calendar event or sends anything.
"""

from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook

INTERVIEWER_POOL_SHEET = "Interviewer Pool"
INTERVIEWER_POOL_COLUMNS = ["Job Title", "Eligible Interviewers"]

INTERVIEW_LOG_SHEET = "Interview Log"
INTERVIEW_LOG_COLUMNS = [
    "Candidate", "Job Title", "Assigned Interviewer", "Candidate Preferred Time",
    "Interviewer Confirmed", "Candidate Confirmed", "Final Scheduled Time", "Status",
]

_SHEET_SPECS = ((INTERVIEWER_POOL_SHEET, INTERVIEWER_POOL_COLUMNS), (INTERVIEW_LOG_SHEET, INTERVIEW_LOG_COLUMNS))


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
        workbook.save(path)
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
        workbook.save(path)

    return {"created": False, "sheets_added": sheets_added, "columns_added": columns_added}


def read_interviewer_pool(path: Path) -> dict[str, list[str]]:
    """Job title -> the list of eligible interviewer names configured for it (parsed from
    the comma-separated "Eligible Interviewers" column). Empty dict if the sheet or its
    expected columns aren't present -- callers treat that as "nothing configured yet", not
    an error."""
    workbook = load_workbook(path, read_only=True, data_only=True)
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
        names = [name.strip() for name in str(interviewers_raw).split(",") if name.strip()]
        pool[str(job_title).strip()] = names
    return pool


def eligible_interviewers_for_job(path: Path, job_title: str) -> list[str]:
    """The eligible interviewer names for one job title -- case/whitespace-normalized
    matching (not fuzzy) against the pool's own Job Title column, since recruiters typing
    the same title into two different systems rarely match byte-for-byte."""
    target = job_title.strip().lower()
    for title, names in read_interviewer_pool(path).items():
        if title.lower() == target:
            return names
    return []


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
    workbook.save(path)
