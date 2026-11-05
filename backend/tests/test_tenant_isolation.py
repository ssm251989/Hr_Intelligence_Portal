"""RLS (docs/HRMS_COMPLETE_SPEC.txt section B + Part 2 section 2) -- two tenants, same
table, no cross reads; a session that never sets app.tenant_id sees nothing (Part 2
CHECKS: "two tenants, same ids -> no cross reads; RLS blocks raw SQL without
app.tenant_id"). Exercises RLS directly via raw SQL, deliberately bypassing the ORM's own
ADDITIONAL app-layer filter (TenantOwned's with_loader_criteria, see
platform/tenancy/mixins.py) -- that filter reads the Python contextvar, a different
mechanism from the Postgres session variable RLS itself reads, and this file's job is to
prove the DB-level enforcement holds even for a query the ORM filter never sees."""

import uuid

import pytest
from sqlalchemy import text

from app.platform.tenancy.context import TENANT_1_ID


def _set_tenant(db_session, tenant_id) -> None:
    db_session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})


def test_two_tenants_same_table_no_cross_reads_via_raw_sql(db_session):
    tenant_2_id = uuid.uuid4()

    _set_tenant(db_session, TENANT_1_ID)
    db_session.execute(
        text("INSERT INTO candidates (id, full_name, tenant_id) VALUES (gen_random_uuid(), :name, :tid)"),
        {"name": "Tenant One Candidate", "tid": str(TENANT_1_ID)},
    )
    _set_tenant(db_session, tenant_2_id)
    db_session.execute(
        text("INSERT INTO candidates (id, full_name, tenant_id) VALUES (gen_random_uuid(), :name, :tid)"),
        {"name": "Tenant Two Candidate", "tid": str(tenant_2_id)},
    )

    _set_tenant(db_session, TENANT_1_ID)
    names = {row[0] for row in db_session.execute(text("SELECT full_name FROM candidates")).fetchall()}
    assert "Tenant One Candidate" in names
    assert "Tenant Two Candidate" not in names

    _set_tenant(db_session, tenant_2_id)
    names = {row[0] for row in db_session.execute(text("SELECT full_name FROM candidates")).fetchall()}
    assert "Tenant Two Candidate" in names
    assert "Tenant One Candidate" not in names


def test_a_session_that_never_sets_app_tenant_id_sees_zero_rows():
    """Uses the `users` table's real, permanently-committed rows (this repo's own dev
    tenant #1 has 20+ real users -- see hrctl.tenant bootstrap-existing) rather than
    anything inserted by this test, specifically so this proves the "unset session sees
    NOTHING" claim against data that genuinely, committedly exists -- not just data this
    same connection/transaction happened to insert (and could trivially still see for
    unrelated reasons)."""
    from tests.conftest import engine as tenant_engine

    # Confirm real data actually exists first, from a connection that DOES set
    # app.tenant_id -- otherwise a 0 count below would prove nothing.
    with tenant_engine.connect() as connection_with_tenant:
        connection_with_tenant.execute(text("SET app.tenant_id = :tid"), {"tid": str(TENANT_1_ID)})
        real_user_count = connection_with_tenant.execute(text("SELECT count(*) FROM users")).scalar()
        assert real_user_count > 0

    with tenant_engine.connect() as connection_without_tenant:
        unset_count = connection_without_tenant.execute(text("SELECT count(*) FROM users")).scalar()
        assert unset_count == 0


def test_cross_tenant_insert_is_rejected_by_the_with_check_clause(db_session):
    """RLS's WITH CHECK (not just USING) matters here -- a session set to tenant 1 must
    not be able to insert a row claiming to belong to some other tenant."""
    other_tenant_id = uuid.uuid4()
    _set_tenant(db_session, TENANT_1_ID)
    with pytest.raises(Exception):
        db_session.execute(
            text("INSERT INTO candidates (id, full_name, tenant_id) VALUES (gen_random_uuid(), :name, :tid)"),
            {"name": "Should Be Rejected", "tid": str(other_tenant_id)},
        )
        db_session.flush()
