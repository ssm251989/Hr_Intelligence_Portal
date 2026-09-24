"""platform/comms/quiet_hours.py -- quiet-hours window logic + digest_mode gating in
dispatch_event (Part 4 CHECKS). Actual scheduled delivery once quiet hours end / a digest
period completes is NOT built (needs live Celery beat -- see this module's own docstring);
these tests cover the "hold or send now" decision, which is what's actually implemented.
"""

from datetime import datetime, timezone

from app.models.comms import NotificationRule, OutboundMessage
from app.platform.connectors.purposes import register_purpose
from app.platform.comms.quiet_hours import is_within_quiet_hours, should_hold_for_digest, should_hold_for_quiet_hours
from app.platform.comms.service import dispatch_event
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_is_within_quiet_hours_true_inside_a_same_day_window():
    quiet_hours = {"start": "13:00", "end": "15:00", "tz": "UTC"}
    now = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    assert is_within_quiet_hours(quiet_hours, now) is True


def test_is_within_quiet_hours_false_outside_a_same_day_window():
    quiet_hours = {"start": "13:00", "end": "15:00", "tz": "UTC"}
    now = datetime(2026, 1, 1, 16, 0, tzinfo=timezone.utc)
    assert is_within_quiet_hours(quiet_hours, now) is False


def test_is_within_quiet_hours_handles_an_overnight_window():
    quiet_hours = {"start": "22:00", "end": "07:00", "tz": "UTC"}
    assert is_within_quiet_hours(quiet_hours, datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)) is True
    assert is_within_quiet_hours(quiet_hours, datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)) is True
    assert is_within_quiet_hours(quiet_hours, datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)) is False


def test_is_within_quiet_hours_false_with_no_quiet_hours_configured():
    assert is_within_quiet_hours(None) is False
    assert is_within_quiet_hours({}) is False


def test_should_hold_for_quiet_hours_respects_the_rule_flag():
    quiet_hours = {"start": "00:00", "end": "23:59", "tz": "UTC"}  # always quiet
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert should_hold_for_quiet_hours(True, quiet_hours, now) is True
    assert should_hold_for_quiet_hours(False, quiet_hours, now) is False


def test_should_hold_for_digest_modes():
    assert should_hold_for_digest("none") is False
    assert should_hold_for_digest("hourly") is True
    assert should_hold_for_digest("daily") is True


def test_dispatch_event_holds_a_digest_mode_rule_instead_of_sending(db_session):
    register_purpose("test.quiet_hours_digest.event")
    db_session.add(NotificationRule(
        tenant_id=TENANT_1_ID, name="digest rule", event_type="test.quiet_hours_digest.event",
        recipients_json={"users": ["someone@example.com"]}, channels=["email"], template_key="does.not.matter",
        digest_mode="daily", priority=1, enabled=True,
    ))
    db_session.commit()

    results = dispatch_event(db_session, TENANT, "test.quiet_hours_digest.event", {})

    assert len(results) == 1
    assert results[0].status == "queued"
    stored = db_session.query(OutboundMessage).filter(OutboundMessage.id == results[0].id).first()
    assert stored.status == "queued"
