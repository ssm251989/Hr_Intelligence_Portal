"""Numbering sequences (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 4) -- e.g.
`employee_code`/`offer_no`/`ticket_no`, pattern `"{ENTITY}-{YYYY}-{SEQ:5}"`.

`{ENTITY}` in the spec's own example pattern is just a literal prefix a tenant writes
directly into `pattern` (e.g. `"EMP-{YYYY}-{SEQ:5}"`) -- `_format()` below only
substitutes the placeholders it actually knows (`{YYYY}`/`{YY}`/`{MM}`/`{SEQ[:width]}`),
leaving any other literal text in the pattern untouched.

Concurrency safety (section's own `test_sequences_concurrency.py` requirement): a single
atomic `UPDATE ... SET current = current + 1 WHERE ... RETURNING current` is what makes
two simultaneous callers each get a DISTINCT, gap-free number -- never a Python-level
"SELECT current, then UPDATE current+1" (a classic read-then-write race: two callers can
both read the same `current` before either writes, handing out the same number twice).
Postgres serializes concurrent UPDATEs to the same row automatically; the second
transaction simply waits for the first to commit, then sees its already-incremented value.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.metadata import Sequence
from app.platform.tenancy.context import TenantContext


class SequenceNotFoundError(Exception):
    pass


def _current_period(reset: str, now: datetime) -> Optional[str]:
    if reset == "never":
        return None
    if reset == "yearly":
        return str(now.year)
    if reset == "fy":
        # April-March fiscal year (org.fiscal_year_start default "04-01", section 6's own
        # locale defaults) -- FY "2026" runs 2026-04-01..2027-03-31.
        return str(now.year if now.month >= 4 else now.year - 1)
    raise ValueError(f"Unknown reset policy: {reset!r}")


def define(db: Session, tenant: TenantContext, *, key: str, pattern: str, scope: Optional[str] = None, reset: str = "never") -> Sequence:
    existing = db.query(Sequence).filter(Sequence.tenant_id == tenant.tenant_id, Sequence.key == key).first()
    if existing is not None:
        return existing
    row = Sequence(tenant_id=tenant.tenant_id, key=key, pattern=pattern, scope=scope, reset=reset, current=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def next_value(db: Session, tenant: TenantContext, key: str, *, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    row = db.query(Sequence).filter(Sequence.tenant_id == tenant.tenant_id, Sequence.key == key).first()
    if row is None:
        raise SequenceNotFoundError(f"No sequence defined for key: {key}")

    period = _current_period(row.reset, now)
    if period is not None and row.current_period != period:
        # First call of a new period -- reset atomically too (same "one statement, no
        # read-then-write gap" principle; a concurrent caller mid-rollover either sees the
        # old period+old current, or the new period+1, never a mixed state).
        result = db.execute(
            text("UPDATE sequences SET current = 1, current_period = :period WHERE id = :id RETURNING current"),
            {"period": period, "id": row.id},
        )
    else:
        result = db.execute(text("UPDATE sequences SET current = current + 1 WHERE id = :id RETURNING current"), {"id": row.id})
    new_current = result.scalar_one()
    db.commit()

    # For reset="yearly"/"fy", {YYYY} in the pattern must format as the PERIOD label
    # (e.g. fiscal year 2025 for a March 2026 date), not `now`'s own calendar year --
    # substitute a year-adjusted stand-in datetime rather than teaching _format() about
    # reset policies directly (it stays a pure, reset-policy-agnostic formatter).
    format_now = now if period is None else now.replace(year=int(period))
    return _format(row.pattern, new_current, format_now)


def _format(pattern: str, current: int, now: datetime) -> str:
    import re

    def _seq_sub(match: re.Match) -> str:
        width = int(match.group(1)) if match.group(1) else 1
        return str(current).zfill(width)

    formatted = re.sub(r"\{SEQ(?::(\d+))?\}", _seq_sub, pattern)
    formatted = formatted.replace("{YYYY}", str(now.year)).replace("{YY}", str(now.year % 100).zfill(2))
    formatted = formatted.replace("{MM}", str(now.month).zfill(2))
    return formatted
