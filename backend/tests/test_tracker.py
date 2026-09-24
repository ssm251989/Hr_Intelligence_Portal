"""app/interview_scheduling/tracker.py -- specifically that reading this workbook never
holds the underlying Excel file locked past the single read that needed it. The tracker is
deliberately meant to be human-editable in Excel at any time (that's the whole point of using
Excel for the Interviewer Pool); a real "sharing violation" opening it while the backend was
running traced back to the three read_only=True loads here never calling workbook.close(),
leaving the OS-level file lock open for however long CPython's cyclic GC took to notice
(openpyxl's internal objects hold reference cycles, so plain refcounting never freed it
promptly) -- confirmed directly: even a bare os.rename() on the file failed with WinError 32
until close() ran.
"""

import sys

import pytest
from openpyxl import load_workbook, Workbook

from app.interview_scheduling import tracker


def _make_tracker(tmp_path):
    path = tmp_path / "tracker.xlsx"
    tracker.ensure_tracker_file(path)
    return path


def _spy_on_close(monkeypatch):
    """Wraps tracker.load_workbook so every returned workbook's .close() call is recorded,
    without depending on OS-specific lock semantics (real file locking is Windows-specific;
    POSIX rename doesn't enforce it, so it can't tell the two cases apart on every platform
    this suite might run on)."""
    closed_count = 0
    real_load_workbook = tracker.load_workbook

    def spy(*args, **kwargs):
        nonlocal closed_count
        workbook = real_load_workbook(*args, **kwargs)
        original_close = workbook.close

        def spy_close():
            nonlocal closed_count
            closed_count += 1
            return original_close()

        workbook.close = spy_close
        return workbook

    monkeypatch.setattr(tracker, "load_workbook", spy)
    return lambda: closed_count


def test_read_mail_directory_closes_its_read_only_workbook(tmp_path, monkeypatch):
    path = _make_tracker(tmp_path)
    workbook = load_workbook(path)
    workbook[tracker.MAILS_SHEET].append(["Kishore", "kg@example.com"])
    workbook.save(path)

    get_closed_count = _spy_on_close(monkeypatch)
    tracker.read_mail_directory(path)

    assert get_closed_count() == 1


def test_interviewer_busy_this_week_closes_its_read_only_workbook(tmp_path, monkeypatch):
    path = _make_tracker(tmp_path)

    get_closed_count = _spy_on_close(monkeypatch)
    tracker.interviewer_busy_this_week(path, "Kishore")

    assert get_closed_count() == 1


def test_read_interviewer_pool_closes_its_read_only_workbook(tmp_path, monkeypatch):
    path = _make_tracker(tmp_path)

    get_closed_count = _spy_on_close(monkeypatch)
    tracker.read_interviewer_pool(path)

    assert get_closed_count() == 1


def test_read_only_loads_close_even_when_the_sheet_is_missing_or_malformed(tmp_path, monkeypatch):
    """The early-return branches (sheet not present, expected columns missing) must still
    close the workbook -- these are exactly the branches most likely to be added without
    the finally block ever being reached if someone edits this later without noticing the
    try/finally wrapping the whole body."""
    from openpyxl import Workbook

    path = tmp_path / "blank.xlsx"
    Workbook().save(path)  # no Interviewer Pool / Interview Log / Mails sheets at all

    get_closed_count = _spy_on_close(monkeypatch)
    assert tracker.read_mail_directory(path) == {}
    assert tracker.interviewer_busy_this_week(path, "Kishore") is False
    assert tracker.read_interviewer_pool(path) == {}

    assert get_closed_count() == 3


@pytest.mark.skipif(sys.platform != "win32", reason="Mandatory file locking on open handles is a Windows-specific behavior")
def test_a_full_pool_walk_read_sequence_leaves_the_file_immediately_editable(tmp_path):
    """The most direct reproduction of the real report: run the same sequence of reads the
    interviewer-pool walk performs for one candidate (read the pool, check busy-this-week,
    look up their email), then confirm the file is NOT locked afterward -- proven the same
    way the bug was originally confirmed, by an os.rename() that would fail with WinError 32
    on any handle still held open."""
    import os

    path = _make_tracker(tmp_path)
    workbook = load_workbook(path)
    workbook[tracker.INTERVIEWER_POOL_SHEET].append(["Automation Anywhere Architect", "Kishore"])
    workbook[tracker.MAILS_SHEET].append(["Kishore", "kg@example.com"])
    workbook.save(path)

    tracker.eligible_interviewers_for_job(path, "Automation Anywhere Architect")
    tracker.interviewer_busy_this_week(path, "Kishore")
    tracker.email_for_interviewer(path, "Kishore")

    renamed = path.with_suffix(".renamed.xlsx")
    os.rename(path, renamed)  # raises PermissionError (WinError 32) if anything left it locked
    os.rename(renamed, path)


def _flaky_save(fail_times: int):
    """Returns a workbook.save replacement raising PermissionError the first `fail_times`
    calls, then succeeding -- simulates the tracker being open in Excel for a few moments
    before the recruiter closes it, without depending on real OS-level file locking (which
    is Windows-specific -- see this module's other tests)."""
    calls = {"count": 0}

    def save(self, path):
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise PermissionError("The process cannot access the file because it is being used by another process")
        return _real_save(self, path)

    return save, calls


_real_save = Workbook.save


def test_save_with_retry_succeeds_once_the_file_stops_being_locked(tmp_path, monkeypatch):
    path = _make_tracker(tmp_path)
    save, calls = _flaky_save(fail_times=2)
    monkeypatch.setattr(Workbook, "save", save)
    monkeypatch.setattr(tracker.time, "sleep", lambda _seconds: None)

    workbook = load_workbook(path)
    tracker._save_with_retry(workbook, path, attempts=5, backoff_s=0)

    assert calls["count"] == 3  # 2 failures then a success, well within the 5-attempt budget


def test_save_with_retry_raises_tracker_file_locked_error_after_exhausting_attempts(tmp_path, monkeypatch):
    path = _make_tracker(tmp_path)
    save, calls = _flaky_save(fail_times=999)  # never succeeds within this test's attempt budget
    monkeypatch.setattr(Workbook, "save", save)
    monkeypatch.setattr(tracker.time, "sleep", lambda _seconds: None)

    workbook = load_workbook(path)
    with pytest.raises(tracker.TrackerFileLockedError):
        tracker._save_with_retry(workbook, path, attempts=3, backoff_s=0)

    assert calls["count"] == 3  # stopped at the attempt budget, not an infinite retry


def test_append_interview_log_row_raises_tracker_file_locked_error_when_always_locked(tmp_path, monkeypatch):
    """A real write path (not _save_with_retry directly) surfaces the same error -- every
    workbook.save(path) call in this module goes through _save_with_retry (see its own
    module-level docstring), so this exercises that wiring end to end."""
    path = _make_tracker(tmp_path)
    save, _calls = _flaky_save(fail_times=999)
    monkeypatch.setattr(Workbook, "save", save)
    monkeypatch.setattr(tracker.time, "sleep", lambda _seconds: None)

    with pytest.raises(tracker.TrackerFileLockedError):
        tracker.append_interview_log_row(path, {"Candidate": "Jane Doe", "Job Title": "Engineer"})


@pytest.mark.parametrize(
    "cell_value, expected",
    [
        ("A,B", ["A", "B"]),
        ("A, B", ["A", "B"]),
        (" A ,B ", ["A", "B"]),
        ("A;B", ["A;B"]),  # ";" is not a recognized separator -- one literal name, not two
        ("A,B,", ["A", "B"]),  # trailing comma
        ("", []),  # empty cell
        ("A,,B", ["A", "B"]),  # empty entry between two real ones
        ("A,B,A", ["A", "B"]),  # duplicate -- deduped, first occurrence's order kept
        ("A,b,B", ["A", "b"]),  # duplicate is case-insensitive -- "B" dropped, "b" kept (first)
    ],
)
def test_read_interviewer_pool_parses_the_eligible_interviewers_cell(tmp_path, cell_value, expected):
    path = _make_tracker(tmp_path)
    workbook = load_workbook(path)
    workbook[tracker.INTERVIEWER_POOL_SHEET].append(["Some Job", cell_value])
    workbook.save(path)

    pool = tracker.read_interviewer_pool(path)

    assert pool["Some Job"] == expected
