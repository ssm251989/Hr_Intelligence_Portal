"""platform/metadata/sequences.py -- pattern formatting, reset policies, and REAL
concurrency safety (Part 6's own explicitly-named test). The concurrency case needs
genuinely separate Postgres connections racing each other -- the shared `db_session`
fixture's single connection/transaction (rolled back at teardown) can't exercise that, so
this one file's concurrency test uses `app.core.database.SessionLocal` directly (real
commits against the real dev DB, same pattern this build's own hrctl scripts/live smoke
tests already use), with explicit try/finally cleanup rather than relying on a rolled-back
transaction.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.metadata import Sequence
from app.platform.metadata.sequences import _format, define, next_value
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_format_pads_the_sequence_number():
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    assert _format("EMP-{YYYY}-{SEQ:5}", 42, now) == "EMP-2026-00042"


def test_format_supports_yy_and_mm():
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    assert _format("{YY}{MM}-{SEQ:3}", 7, now) == "2606-007"


def test_next_value_increments_and_formats(db_session):
    define(db_session, TENANT, key="test.offer_no", pattern="OFR-{YYYY}-{SEQ:4}", reset="never")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert next_value(db_session, TENANT, "test.offer_no", now=now) == "OFR-2026-0001"
    assert next_value(db_session, TENANT, "test.offer_no", now=now) == "OFR-2026-0002"


def test_yearly_reset_starts_over_in_a_new_year(db_session):
    define(db_session, TENANT, key="test.ticket_no", pattern="TKT-{YYYY}-{SEQ:3}", reset="yearly")
    assert next_value(db_session, TENANT, "test.ticket_no", now=datetime(2026, 12, 31, tzinfo=timezone.utc)) == "TKT-2026-001"
    assert next_value(db_session, TENANT, "test.ticket_no", now=datetime(2026, 12, 31, tzinfo=timezone.utc)) == "TKT-2026-002"
    assert next_value(db_session, TENANT, "test.ticket_no", now=datetime(2027, 1, 1, tzinfo=timezone.utc)) == "TKT-2027-001"


def test_fy_reset_uses_april_as_the_fiscal_year_boundary(db_session):
    define(db_session, TENANT, key="test.fy_seq", pattern="FY{YYYY}-{SEQ:2}", reset="fy")
    # March 2026 is still FY2025 (Apr 2025 -- Mar 2026)
    assert next_value(db_session, TENANT, "test.fy_seq", now=datetime(2026, 3, 15, tzinfo=timezone.utc)) == "FY2025-01"
    # April 2026 starts FY2026 -- resets
    assert next_value(db_session, TENANT, "test.fy_seq", now=datetime(2026, 4, 1, tzinfo=timezone.utc)) == "FY2026-01"


def test_concurrent_next_value_calls_never_hand_out_a_duplicate():
    """20 threads x 5 calls each = 100 real concurrent increments against a real,
    committed row, each thread on its OWN connection -- proves the atomic `UPDATE ...
    RETURNING` (not a Python-level read-then-write) actually serializes correctly under
    real contention, not just in a single-threaded/single-connection test."""
    key = f"test.concurrency.{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        with tenant_context(TENANT_1_ID):
            define(db, TENANT, key=key, pattern="CNC-{SEQ:5}", reset="never")
    finally:
        db.close()

    def _worker(_i):
        results = []
        worker_db = SessionLocal()
        try:
            with tenant_context(TENANT_1_ID):
                for _ in range(5):
                    results.append(next_value(worker_db, TENANT, key))
        finally:
            worker_db.close()
        return results

    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            all_results = [r for batch in pool.map(_worker, range(20)) for r in batch]

        assert len(all_results) == 100
        assert len(set(all_results)) == 100, "duplicate sequence value handed out under concurrency"
        assert sorted(all_results) == [f"CNC-{n:05d}" for n in range(1, 101)]
    finally:
        cleanup_db = SessionLocal()
        try:
            with tenant_context(TENANT_1_ID):
                cleanup_db.query(Sequence).filter(Sequence.tenant_id == TENANT_1_ID, Sequence.key == key).delete()
                cleanup_db.commit()
        finally:
            cleanup_db.close()
