"""platform/comms/suppression.py (Part 4 CHECKS)."""

from app.models.comms import NotificationPreference
from app.platform.comms.suppression import filter_suppressed_and_opted_out, is_opted_in, is_suppressed, suppress
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_address_not_suppressed_by_default(db_session):
    assert is_suppressed(db_session, TENANT, "never-suppressed@example.com") is False


def test_suppress_then_is_suppressed(db_session):
    suppress(db_session, TENANT, "bounced@example.com", "bounce")
    assert is_suppressed(db_session, TENANT, "bounced@example.com") is True


def test_suppress_is_case_insensitive(db_session):
    suppress(db_session, TENANT, "Bounced@Example.com", "bounce")
    assert is_suppressed(db_session, TENANT, "bounced@example.com") is True


def test_suppress_twice_is_idempotent(db_session):
    suppress(db_session, TENANT, "dup@example.com", "bounce")
    suppress(db_session, TENANT, "dup@example.com", "unsubscribe")  # must not raise (unique constraint)
    assert is_suppressed(db_session, TENANT, "dup@example.com") is True


def test_filter_suppressed_and_opted_out_removes_suppressed_addresses(db_session):
    suppress(db_session, TENANT, "blocked@example.com", "complaint")
    result = filter_suppressed_and_opted_out(
        db_session, TENANT, ["blocked@example.com", "fine@example.com"], channel="email", event_group="test.group",
    )
    assert result == ["fine@example.com"]


def test_opted_in_defaults_true_with_no_preference_row(db_session):
    import uuid

    assert is_opted_in(db_session, TENANT, user_id=uuid.uuid4(), channel="email", event_group="test.group") is True


def test_opted_in_false_after_an_explicit_opt_out_row(db_session):
    import uuid

    user_id = uuid.uuid4()
    db_session.add(NotificationPreference(tenant_id=TENANT_1_ID, user_id=user_id, channel="email", event_group="test.group", opted_in=False))
    db_session.commit()

    assert is_opted_in(db_session, TENANT, user_id=user_id, channel="email", event_group="test.group") is False


def test_opted_in_for_a_candidate_is_independent_of_users(db_session):
    import uuid

    candidate_id = uuid.uuid4()
    db_session.add(NotificationPreference(tenant_id=TENANT_1_ID, candidate_id=candidate_id, channel="email", event_group="test.group", opted_in=False))
    db_session.commit()

    assert is_opted_in(db_session, TENANT, candidate_id=candidate_id, channel="email", event_group="test.group") is False
    assert is_opted_in(db_session, TENANT, candidate_id=uuid.uuid4(), channel="email", event_group="test.group") is True
