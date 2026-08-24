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
from openpyxl import load_workbook

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
