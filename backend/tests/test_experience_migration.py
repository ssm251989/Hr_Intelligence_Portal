"""Unit tests for alembic/versions/b8f3c1e7a4d2_replace_experience_level_with_min_max_
years.py's best-effort experience_level -> experience_min_years/experience_max_years
parsing -- loaded directly from its file path (alembic version files aren't a real
Python package) so its pure helper functions can be exercised without a live alembic
migration context, which op.get_bind()-based code (upgrade()/downgrade() themselves)
requires and a plain unit test can't provide.
"""
import importlib.util
import logging
import uuid
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "b8f3c1e7a4d2_replace_experience_level_with_min_max_years.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("experience_migration_b8f3c1e7a4d2", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


# --- _parse_experience_level: best-effort text -> (min, max) ---


def test_parse_experience_level_range():
    assert migration._parse_experience_level("3-5 years") == (3.0, 5.0)


def test_parse_experience_level_range_with_decimals_and_yrs_abbreviation():
    assert migration._parse_experience_level("3.5-5.5 yrs") == (3.5, 5.5)


def test_parse_experience_level_plus_is_open_ended_max():
    assert migration._parse_experience_level("5+ years") == (5.0, None)


def test_parse_experience_level_exact_single_number_is_min_equals_max():
    assert migration._parse_experience_level("5 years") == (5.0, 5.0)
    assert migration._parse_experience_level("5") == (5.0, 5.0)


def test_parse_experience_level_blank_or_none_is_not_an_unparsed_failure():
    # Empty/whitespace/None means "nothing was ever entered" -- treated the same as a
    # clean (None, None), never counted as a row that "couldn't be parsed."
    assert migration._parse_experience_level(None) == (None, None)
    assert migration._parse_experience_level("") == (None, None)
    assert migration._parse_experience_level("   ") == (None, None)


def test_parse_experience_level_free_text_label_is_unparsed():
    # Free-text labels this migration deliberately never guesses at.
    for label in ("Senior", "Mid-level", "Entry level", "N/A", "Fresher"):
        assert migration._parse_experience_level(label) == (None, None)


# --- _classify_rows: splits (id, experience_level) rows into parsed vs unparsed ---


def test_classify_rows_splits_parsed_from_unparsed():
    id_range, id_plus, id_exact, id_label, id_blank = (uuid.uuid4() for _ in range(5))
    rows = [
        (id_range, "3-5 years"),
        (id_plus, "5+ years"),
        (id_exact, "5 years"),
        (id_label, "Senior"),
        (id_blank, ""),
    ]

    parsed, unparsed = migration._classify_rows(rows)

    parsed_by_id = {row[0]: row[1:] for row in parsed}
    assert parsed_by_id[id_range] == (3.0, 5.0)
    assert parsed_by_id[id_plus] == (5.0, None)
    assert parsed_by_id[id_exact] == (5.0, 5.0)
    assert id_blank not in parsed_by_id  # blank never produces an UPDATE either

    assert unparsed == [(id_label, "Senior")]


def test_classify_rows_all_clean_leaves_unparsed_empty():
    rows = [(uuid.uuid4(), "2-4 years"), (uuid.uuid4(), "6+ years")]
    parsed, unparsed = migration._classify_rows(rows)
    assert len(parsed) == 2
    assert unparsed == []


def test_classify_rows_all_unparseable():
    rows = [(uuid.uuid4(), "Senior"), (uuid.uuid4(), "Junior")]
    parsed, unparsed = migration._classify_rows(rows)
    assert parsed == []
    assert len(unparsed) == 2


# --- _log_unparsed_rows: unparseable rows are surfaced for manual review, not silent ---


def test_log_unparsed_rows_logs_a_warning_naming_every_row(caplog):
    job_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        migration._log_unparsed_rows([(job_id, "Senior")])

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "1 job_roles row" in message
    assert str(job_id) in message
    assert "Senior" in message


def test_log_unparsed_rows_no_op_when_nothing_unparsed(caplog):
    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        migration._log_unparsed_rows([])
    assert caplog.records == []
