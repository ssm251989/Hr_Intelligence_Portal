"""Replace job_roles.experience_level (free text) with numeric
experience_min_years/experience_max_years.

Dropped experience_level outright rather than keeping it alongside the new columns: this
dev DB's job_roles table is empty at the time of writing (a prior full data reset), so
there is no real data at risk, and there is no reader left in the codebase for the old
column once this migration's callers are updated -- keeping it would just be schema debt
with no path to ever using it again. A deployment with real job_roles data should review
the logged unparsed rows *before* running this migration, since best-effort parsing can't
recover a value like "Senior" or "5+" written in a form this migration doesn't recognize.

Revision ID: b8f3c1e7a4d2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-21 10:00:00.000000

"""
import logging
import re
from typing import Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8f3c1e7a4d2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# Recognizes "3-5 years", "5+ years", "5 years", "5", "3.5-5.5 yrs" -- anything else
# (free-text labels like "Senior", "Mid-level", "Entry level", "N/A") is left unparsed
# and logged for manual review rather than guessed at.
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")
_PLUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+")
_EXACT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:years?|yrs?)?$")


def _parse_experience_level(raw: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    text = (raw or "").strip().lower()
    if not text:
        return None, None
    match = _RANGE_RE.search(text)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = _PLUS_RE.search(text)
    if match:
        return float(match.group(1)), None
    match = _EXACT_RE.match(text)
    if match:
        value = float(match.group(1))
        return value, value
    return None, None


def _classify_rows(
    rows: list[tuple],
) -> tuple[list[tuple[object, float, Optional[float]]], list[tuple[object, str]]]:
    """Splits (id, experience_level) rows into ones that parsed cleanly (ready for an
    UPDATE) and ones that didn't (left null, for manual review) -- pure, no DB access, so
    it's unit-testable without a live alembic migration context. `min_years` is never None
    in a parsed row (see _parse_experience_level: the only way min is None is if max is
    too, which makes the row unparsed instead). A blank/whitespace-only value is treated
    as "nothing was ever entered," same as the NULL rows the caller's query already
    excludes -- never logged as an unparsed row needing manual review, unlike a genuine
    free-text label such as "Senior" that actually held information now being dropped."""
    parsed: list[tuple[object, float, Optional[float]]] = []
    unparsed: list[tuple[object, str]] = []
    for job_id, raw_value in rows:
        min_years, max_years = _parse_experience_level(raw_value)
        if min_years is not None or max_years is not None:
            parsed.append((job_id, min_years, max_years))
        elif (raw_value or "").strip():
            unparsed.append((job_id, raw_value))
    return parsed, unparsed


def _log_unparsed_rows(unparsed: list[tuple[object, str]]) -> None:
    """Split out from upgrade() purely so a test can call it directly with a fabricated
    `unparsed` list and assert on the log record, without needing a live alembic
    migration context (op.get_bind() only works inside a real migration run)."""
    if not unparsed:
        return
    logger.warning(
        "experience_level migration: %d job_roles row(s) had an experience_level "
        "value that could not be parsed into a numeric range and were left with "
        "null experience_min_years/experience_max_years -- review manually: %s",
        len(unparsed),
        [(str(job_id), raw_value) for job_id, raw_value in unparsed],
    )


def upgrade() -> None:
    op.add_column('job_roles', sa.Column('experience_min_years', sa.Numeric(), nullable=True))
    op.add_column('job_roles', sa.Column('experience_max_years', sa.Numeric(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, experience_level FROM job_roles WHERE experience_level IS NOT NULL")
    ).fetchall()
    parsed, unparsed = _classify_rows(rows)

    for job_id, min_years, max_years in parsed:
        bind.execute(
            sa.text(
                "UPDATE job_roles SET experience_min_years = :min_years, "
                "experience_max_years = :max_years WHERE id = :id"
            ),
            {"min_years": min_years, "max_years": max_years, "id": job_id},
        )

    _log_unparsed_rows(unparsed)
    op.drop_column('job_roles', 'experience_level')


def downgrade() -> None:
    op.add_column('job_roles', sa.Column('experience_level', sa.String(length=100), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, experience_min_years, experience_max_years FROM job_roles")
    ).fetchall()
    for job_id, min_years, max_years in rows:
        if min_years is None and max_years is None:
            continue
        if max_years is None:
            text_value = f"{min_years:g}+ years"
        elif min_years == max_years:
            text_value = f"{min_years:g} years"
        else:
            text_value = f"{min_years:g}-{max_years:g} years"
        bind.execute(
            sa.text("UPDATE job_roles SET experience_level = :val WHERE id = :id"),
            {"val": text_value, "id": job_id},
        )

    op.drop_column('job_roles', 'experience_min_years')
    op.drop_column('job_roles', 'experience_max_years')
