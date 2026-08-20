"""Unit tests for alembic/versions/c4d9e2a7f5b1_replace_skills_with_categorized_lists.py's
one-time best-effort default categorization (every pre-existing skill moved into
technical_skills_must_have) -- loaded directly from its file path (alembic version files
aren't a real Python package) so its pure helper can be exercised without a live alembic
migration context, which op.get_bind()-based code (upgrade()/downgrade() themselves)
requires and a plain unit test can't provide.
"""
import importlib.util
import logging
import uuid
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "c4d9e2a7f5b1_replace_skills_with_categorized_lists.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("skills_migration_c4d9e2a7f5b1", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_log_default_categorization_logs_an_info_record_naming_every_job(caplog):
    job_id = uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        migration._log_default_categorization([(job_id, ["Python", "SQL"])])

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert "1 job_roles row" in message
    assert str(job_id) in message
    assert "Python" in message and "SQL" in message
    # Explicit that this is a default, not a real categorization -- the whole point of
    # logging it at all.
    assert "best-effort default" in message


def test_log_default_categorization_names_every_job_when_more_than_one(caplog):
    job_a, job_b = uuid.uuid4(), uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        migration._log_default_categorization([(job_a, ["Python"]), (job_b, ["Excel"])])

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "2 job_roles row" in message
    assert str(job_a) in message
    assert str(job_b) in message


def test_log_default_categorization_no_op_when_nothing_to_migrate(caplog):
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        migration._log_default_categorization([])
    assert caplog.records == []
