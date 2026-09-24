"""platform/settings/resolver.py -- scope precedence, validation, cache invalidation (Part
2 CHECKS)."""

import uuid

import pytest

from app.platform.settings import bootstrap_definitions
from app.platform.settings.registry import SettingAlreadyRegisteredError, SettingDef, UnknownSettingError, get_definition, register
from app.platform.settings.resolver import SettingContext, SettingsService, clear_all_cache
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

bootstrap_definitions.register_all()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    clear_all_cache()
    yield
    clear_all_cache()


def _tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def test_bootstrap_definitions_registered_every_section_6_group():
    for key in (
        "org.display_name", "org.timezone",
        "recruitment.screening.auto_shortlist_threshold",
        "recruitment.negotiation.slots_offered", "recruitment.negotiation.slots_to_pick",
        "recruitment.tracker.save_retry.attempts",
        "ai.models.resume_extraction", "ai.models.candidate_ranking",
    ):
        setting_def = get_definition(key)
        assert setting_def.key == key


def test_get_falls_back_to_platform_default_when_nothing_is_set(db_session):
    ctx = SettingContext(tenant=_tenant_ctx())
    service = SettingsService(db_session)
    assert service.get("recruitment.negotiation.slots_offered", ctx) == 3


def test_set_then_get_returns_the_tenant_scoped_value(db_session):
    ctx = SettingContext(tenant=_tenant_ctx())
    service = SettingsService(db_session)
    service.set(
        "recruitment.negotiation.slots_offered", 4, scope_type="tenant", scope_id=None,
        actor="admin@example.com", tenant=_tenant_ctx(),
    )
    assert service.get("recruitment.negotiation.slots_offered", ctx) == 4


def test_user_scope_wins_over_tenant_scope(db_session):
    """Layered resolution (section D): user -> ... -> tenant -> platform default. A value
    set for a specific user must be returned instead of the tenant-wide one, when that
    user is the one asking."""
    register(SettingDef("test.user_scoped_setting", "int", 0, module="test", scopes_allowed=("user", "tenant")), replace=True)
    user_id = uuid.uuid4()
    tenant = _tenant_ctx()
    service = SettingsService(db_session)
    service.set(
        "test.user_scoped_setting", 4, scope_type="tenant", scope_id=None,
        actor="admin@example.com", tenant=tenant,
    )
    service.set(
        "test.user_scoped_setting", 9, scope_type="user", scope_id=user_id,
        actor="admin@example.com", tenant=tenant,
    )

    ctx_for_that_user = SettingContext(tenant=tenant, scope_ids={"user": user_id})
    ctx_for_someone_else = SettingContext(tenant=tenant, scope_ids={"user": uuid.uuid4()})

    assert service.get("test.user_scoped_setting", ctx_for_that_user) == 9
    # A different user with nothing set for them falls through to the tenant-wide value.
    assert service.get("test.user_scoped_setting", ctx_for_someone_else) == 4


def test_set_validates_against_the_registered_scopes_allowed(db_session):
    register(SettingDef("test.tenant_only_setting", "str", "default", module="test", scopes_allowed=("tenant",)), replace=True)
    service = SettingsService(db_session)
    with pytest.raises(ValueError):
        service.set(
            "test.tenant_only_setting", "x", scope_type="user", scope_id=uuid.uuid4(),
            actor="admin@example.com", tenant=_tenant_ctx(),
        )


def test_set_runs_custom_validators_and_rejects_bad_values(db_session):
    def _must_be_positive(value):
        if value <= 0:
            raise ValueError("must be positive")

    register(
        SettingDef("test.positive_int", "int", 1, module="test", validators=(_must_be_positive,)),
        replace=True,
    )
    service = SettingsService(db_session)
    with pytest.raises(ValueError):
        service.set("test.positive_int", -5, scope_type="tenant", scope_id=None, actor="admin@example.com", tenant=_tenant_ctx())


def test_get_definition_raises_for_an_unregistered_key():
    with pytest.raises(UnknownSettingError):
        get_definition("does.not.exist")


def test_register_rejects_a_true_duplicate_key():
    register(SettingDef("test.dup_check", "str", "a", module="test"), replace=True)
    with pytest.raises(SettingAlreadyRegisteredError):
        register(SettingDef("test.dup_check", "str", "b", module="test"))


def test_history_records_every_write_in_order(db_session):
    tenant = _tenant_ctx()
    service = SettingsService(db_session)
    service.set(
        "recruitment.negotiation.slots_offered", 4, scope_type="tenant", scope_id=None,
        actor="first@example.com", tenant=tenant,
    )
    service.set(
        "recruitment.negotiation.slots_offered", 5, scope_type="tenant", scope_id=None,
        actor="second@example.com", tenant=tenant,
    )
    ctx = SettingContext(tenant=tenant)
    history = service.history("recruitment.negotiation.slots_offered", ctx)
    assert [h.value_json for h in history] == [5, 4]
    assert [h.updated_by for h in history] == ["second@example.com", "first@example.com"]


def test_cache_invalidates_on_write_within_the_same_session(db_session):
    """A stale cached read must never survive this SAME session's own write -- the
    invalidation path a Redis pub/sub cache would also need to get right, just done
    synchronously and in-process here instead (see resolver.py's own module docstring)."""
    ctx = SettingContext(tenant=_tenant_ctx())
    service = SettingsService(db_session)
    assert service.get("recruitment.negotiation.slots_to_pick", ctx) == 2  # populates the cache

    service.set(
        "recruitment.negotiation.slots_to_pick", 3, scope_type="tenant", scope_id=None,
        actor="admin@example.com", tenant=_tenant_ctx(),
    )
    assert service.get("recruitment.negotiation.slots_to_pick", ctx) == 3
