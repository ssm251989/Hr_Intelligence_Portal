"""platform/connectors/router.py -- priority, conditions, fallback chain, breaker (Part 3
CHECKS). Uses synthetic "test.*" purposes throughout (registered fresh, never
docs/HRMS_COMPLETE_SPEC.txt's own real purpose names) -- this repo's own dev tenant #1
already has REAL routes for the real purposes (see hrctl.migrate_connections, actually run
against this database), which would otherwise collide with whatever this file creates."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.connection import Connection, ConnectionAttempt, ConnectionRoute
from app.platform.connectors.purposes import register_purpose
from app.platform.connectors.router import CIRCUIT_BREAKER_THRESHOLD, ConnectorRouter, NoConnectionForPurposeError
from app.platform.tenancy.context import TENANT_1_ID

TEST_PURPOSE = "test.router.purpose"
TEST_PURPOSE_SPECIFIC = "test.router.specific"
TEST_PURPOSE_MIDDLE = "test.router.middle"
register_purpose(TEST_PURPOSE)
register_purpose(TEST_PURPOSE_MIDDLE, fallback=TEST_PURPOSE)
register_purpose(TEST_PURPOSE_SPECIFIC, fallback=TEST_PURPOSE_MIDDLE)


def _make_connection(db_session, *, provider="smtp", status="active", name="conn") -> Connection:
    conn = Connection(tenant_id=TENANT_1_ID, name=name, provider_code=provider, capability=["EmailSender"], config_json={}, status=status)
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


def _make_route(db_session, *, purpose, connection, priority=1, condition=None, enabled=True) -> ConnectionRoute:
    route = ConnectionRoute(
        tenant_id=TENANT_1_ID, purpose=purpose, connection_id=connection.id, priority=priority,
        condition_jsonlogic=condition, enabled=enabled,
    )
    db_session.add(route)
    db_session.commit()
    return route


def test_resolve_returns_the_highest_priority_enabled_route(db_session):
    low_priority = _make_connection(db_session, name="low")
    high_priority = _make_connection(db_session, name="high")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=low_priority, priority=5)
    _make_route(db_session, purpose=TEST_PURPOSE, connection=high_priority, priority=1)

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE)

    assert resolved.connection.name == "high"


def test_resolve_skips_a_route_whose_condition_fails(db_session):
    wrong = _make_connection(db_session, name="wrong")
    right = _make_connection(db_session, name="right")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=wrong, priority=1, condition={"==": [{"var": "legal_entity"}, "other-entity"]})
    _make_route(db_session, purpose=TEST_PURPOSE, connection=right, priority=2)

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE, ctx={"legal_entity": "main-entity"})

    assert resolved.connection.name == "right"


def test_resolve_matches_a_route_whose_condition_passes(db_session):
    matching = _make_connection(db_session, name="matching")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=matching, priority=1, condition={"==": [{"var": "legal_entity"}, "main-entity"]})

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE, ctx={"legal_entity": "main-entity"})

    assert resolved.connection.name == "matching"


def test_resolve_falls_back_to_the_more_general_purpose(db_session):
    default_conn = _make_connection(db_session, name="default-conn")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=default_conn)
    # Nothing routed for TEST_PURPOSE_SPECIFIC itself -- must fall through its registered
    # chain (specific -> middle -> TEST_PURPOSE) to find this.

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE_SPECIFIC)

    assert resolved.connection.name == "default-conn"
    assert resolved.purpose_resolved == TEST_PURPOSE


def test_resolve_raises_no_connection_for_purpose_when_nothing_matches(db_session):
    with pytest.raises(NoConnectionForPurposeError):
        ConnectorRouter(db_session).resolve(TEST_PURPOSE)


def test_try_resolve_returns_none_instead_of_raising(db_session):
    assert ConnectorRouter(db_session).try_resolve(TEST_PURPOSE) is None


def test_disabled_route_is_skipped(db_session):
    conn = _make_connection(db_session)
    _make_route(db_session, purpose=TEST_PURPOSE, connection=conn, enabled=False)

    with pytest.raises(NoConnectionForPurposeError):
        ConnectorRouter(db_session).resolve(TEST_PURPOSE)


def test_circuit_breaker_skips_a_connection_with_too_many_consecutive_failures(db_session):
    failing = _make_connection(db_session, name="failing")
    healthy = _make_connection(db_session, name="healthy")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=failing, priority=1)
    _make_route(db_session, purpose=TEST_PURPOSE, connection=healthy, priority=2)

    for _ in range(CIRCUIT_BREAKER_THRESHOLD):
        db_session.add(ConnectionAttempt(
            tenant_id=TENANT_1_ID, connection_id=failing.id, purpose=TEST_PURPOSE,
            operation="send", status="failed", created_at=datetime.now(timezone.utc),
        ))
    db_session.commit()

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE)

    assert resolved.connection.name == "healthy"


def test_circuit_breaker_does_not_trip_on_fewer_than_threshold_failures(db_session):
    conn = _make_connection(db_session, name="mostly-fine")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=conn, priority=1)

    for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
        db_session.add(ConnectionAttempt(
            tenant_id=TENANT_1_ID, connection_id=conn.id, purpose=TEST_PURPOSE,
            operation="send", status="failed", created_at=datetime.now(timezone.utc),
        ))
    db_session.commit()

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE)

    assert resolved.connection.name == "mostly-fine"


def test_circuit_breaker_resets_after_a_more_recent_success(db_session):
    # Explicit, unambiguously-increasing timestamps -- rapid sequential datetime.now()
    # calls can land on the same tick under coarser OS clock resolution, and
    # ORDER BY created_at DESC LIMIT N has no secondary tiebreaker, so relying on
    # wall-clock ordering here would be flaky (found the hard way writing this test).
    conn = _make_connection(db_session, name="recovered")
    _make_route(db_session, purpose=TEST_PURPOSE, connection=conn, priority=1)

    base = datetime.now(timezone.utc)
    for i in range(CIRCUIT_BREAKER_THRESHOLD):
        db_session.add(ConnectionAttempt(
            tenant_id=TENANT_1_ID, connection_id=conn.id, purpose=TEST_PURPOSE,
            operation="send", status="failed", created_at=base + timedelta(seconds=i),
        ))
    db_session.add(ConnectionAttempt(
        tenant_id=TENANT_1_ID, connection_id=conn.id, purpose=TEST_PURPOSE,
        operation="send", status="sent", created_at=base + timedelta(seconds=CIRCUIT_BREAKER_THRESHOLD),
    ))
    db_session.commit()

    resolved = ConnectorRouter(db_session).resolve(TEST_PURPOSE)

    assert resolved.connection.name == "recovered"
