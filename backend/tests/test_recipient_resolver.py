"""platform/comms/recipients.py's RecipientResolver (Part 4 CHECKS)."""

import pytest

from app.platform.comms.recipients import RecipientResolutionError, RecipientResolver
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

register_settings_definitions()
TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_relation_candidate_resolves_from_event_context(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"relation": "candidate"}, {"candidate_email": "jane@example.com"})
    assert result == ["jane@example.com"]


def test_relation_application_interviewers_resolves_a_list_from_event_context(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"relation": "application.interviewers"}, {"interviewer_emails": ["a@example.com", "b@example.com"]})
    assert result == ["a@example.com", "b@example.com"]


def test_relation_candidate_returns_empty_when_event_context_lacks_it(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    assert resolver.resolve({"relation": "candidate"}, {}) == []


def test_relation_with_no_registered_resolver_raises(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    with pytest.raises(RecipientResolutionError):
        resolver.resolve({"relation": "employee.manager", "levels": 1}, {})


def test_users_list_of_plain_emails(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"users": ["a@example.com", "b@example.com"]}, {})
    assert result == ["a@example.com", "b@example.com"]


def test_users_list_resolves_a_real_user_id_to_their_email(db_session, make_auth_headers):
    from app.models.user import User

    user = User(email="resolved-user@example.com", hashed_password="x", full_name="Test", role="admin")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"users": [str(user.id)]}, {})
    assert result == ["resolved-user@example.com"]


def test_emails_setting_reads_a_comma_separated_setting_value(db_session):
    from app.platform.settings.registry import SettingDef, register

    register(SettingDef("test.recipients.cc_list", "str", "", module="test"), replace=True)
    SettingsService(db_session).set(
        "test.recipients.cc_list", "one@example.com, two@example.com", scope_type="tenant", scope_id=None,
        actor="admin@example.com", tenant=TENANT,
    )

    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"emails_setting": "test.recipients.cc_list"}, {})
    assert result == ["one@example.com", "two@example.com"]


def test_expression_jsonlogic_resolves_from_event_context(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    result = resolver.resolve({"expression": {"var": "sender_email"}}, {"sender_email": "sender@example.com"})
    assert result == ["sender@example.com"]


def test_role_scope_recipient_raises_not_yet_implemented(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    with pytest.raises(RecipientResolutionError):
        resolver.resolve({"role": "HRBP", "scope": "employee.location"}, {})


def test_unrecognized_shape_raises(db_session):
    resolver = RecipientResolver(db_session, TENANT)
    with pytest.raises(RecipientResolutionError):
        resolver.resolve({"something_unknown": True}, {})
