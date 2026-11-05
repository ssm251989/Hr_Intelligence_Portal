"""platform/comms/rules.py's NotificationRuleMatcher (Part 4 CHECKS)."""

from app.models.comms import NotificationRule
from app.platform.comms.rules import NotificationRuleMatcher
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_rule(db_session, *, event_type, condition=None, priority=1, enabled=True, name="rule") -> NotificationRule:
    rule = NotificationRule(
        tenant_id=TENANT_1_ID, name=name, event_type=event_type, condition_jsonlogic=condition,
        recipients_json={"relation": "candidate"}, channels=["email"], template_key="test.key",
        priority=priority, enabled=enabled,
    )
    db_session.add(rule)
    db_session.commit()
    return rule


def test_matches_an_enabled_rule_with_no_condition(db_session):
    _make_rule(db_session, event_type="test.event.matching_1")
    matches = NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_1", {})
    assert len(matches) == 1


def test_does_not_match_a_disabled_rule(db_session):
    _make_rule(db_session, event_type="test.event.matching_2", enabled=False)
    matches = NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_2", {})
    assert matches == []


def test_does_not_match_a_different_event_type(db_session):
    _make_rule(db_session, event_type="test.event.matching_3")
    matches = NotificationRuleMatcher(db_session).match(TENANT, "test.event.something_else", {})
    assert matches == []


def test_condition_gates_the_match(db_session):
    _make_rule(db_session, event_type="test.event.matching_4", condition={"==": [{"var": "urgent"}, True]})
    assert NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_4", {"urgent": False}) == []
    matched = NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_4", {"urgent": True})
    assert len(matched) == 1


def test_results_ordered_by_priority(db_session):
    _make_rule(db_session, event_type="test.event.matching_5", priority=5, name="low")
    _make_rule(db_session, event_type="test.event.matching_5", priority=1, name="high")
    matches = NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_5", {})
    assert [r.name for r in matches] == ["high", "low"]


def test_multiple_matching_rules_all_returned(db_session):
    _make_rule(db_session, event_type="test.event.matching_6", name="a")
    _make_rule(db_session, event_type="test.event.matching_6", name="b")
    matches = NotificationRuleMatcher(db_session).match(TENANT, "test.event.matching_6", {})
    assert {r.name for r in matches} == {"a", "b"}
