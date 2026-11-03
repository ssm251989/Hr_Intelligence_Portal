"""Part 23.3f: the Settings letter / email samples had fixed dates and went stale ("sign by 14 October" on a letter
dated 2 November). Sample dates now follow today's date."""
from datetime import date, datetime

from app.experience.ui_design_router import SAMPLE_LETTERS, sample_dates, sample_letter


def _parse(text):
    return datetime.strptime(text, "%d %B %Y").date()


def test_sample_dates_follow_today():
    for today in (date(2026, 11, 2), date(2026, 12, 20), date(2027, 2, 27)):
        d = sample_dates(today)
        sign_by, join = _parse(d["sign_by"]), _parse(d["join"])
        assert today < sign_by < join
        assert join.weekday() == 0 and (join - today).days >= 21
        assert _parse(d["confirm"]) > join
        assert _parse(d["lwd"]) < today


def test_every_sample_letter_is_filled():
    for kind in SAMPLE_LETTERS:
        body = sample_letter(kind, "Acme")
        assert "{" not in body and "}" not in body  # every placeholder filled
        assert str(date.today().year) in body or str(date.today().year + 1) in body
