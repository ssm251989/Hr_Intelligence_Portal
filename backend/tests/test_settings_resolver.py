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
        "recruitment.scoring.shortlist_threshold",  # Part 17.4 replaced recruitment.screening.*
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


# --- type + json_schema validation on save (a bad value used to be stored and crash readers) ---

@pytest.mark.parametrize("key, bad", [
    ("recruitment.scoring.shortlist_threshold", None),       # int, default 75: null not allowed
    ("recruitment.scoring.shortlist_threshold", "abc"),      # int: wrong type
    ("recruitment.scoring.shortlist_threshold", 75.5),       # int: not a whole number
    ("recruitment.scoring.shortlist_threshold", True),       # bool is not an int
    ("recruitment.scoring.shortlist_threshold", 500),        # schema maximum 100
    ("recruitment.scoring.shortlist_threshold", -5),         # schema minimum 0
    ("iam.auth.mfa_required", "yes"),                        # bool: wrong type
    ("org.display_name", 42),                                # str: wrong type
    ("org.support_email", "not-an-email"),                   # email: bad format
    ("recruitment.negotiation.busy_source", "outlook"),      # enum: not in the list
    ("recruitment.salary.reminder_hours", [24, 0]),          # json array item below minimum 1
    ("recruitment.salary.reminder_hours", [1, 2, 3, 4, 5, 6]),  # maxItems 5
])
def test_validate_rejects_values_of_the_wrong_type_or_outside_the_schema(key, bad):
    with pytest.raises(ValueError):
        get_definition(key).validate(bad)


@pytest.mark.parametrize("key, good", [
    ("recruitment.scoring.shortlist_threshold", 0),
    ("recruitment.scoring.shortlist_threshold", 100),
    ("copilot.min_confidence", 1),                           # decimal accepts an int
    ("org.support_email", ""),                               # empty email = not set
    ("org.support_email", "hr@example.com"),
    ("recruitment.salary.reminder_hours", [24, 48]),
])
def test_validate_accepts_valid_values(key, good):
    get_definition(key).validate(good)


def test_every_registered_default_passes_its_own_validation():
    from app.platform.settings.registry import all_definitions

    for setting_def in all_definitions():
        setting_def.validate(setting_def.default)


def test_settings_api_rejects_a_bad_value_with_400_and_keeps_the_old_one(client):
    key = "recruitment.scoring.shortlist_threshold"
    before = {r["key"]: r["value"] for r in client.get("/api/v1/settings").json()}[key]
    for bad in (None, "abc", 500):
        response = client.put(f"/api/v1/settings/{key}", json={"value": bad})
        assert response.status_code == 400, bad
    after = {r["key"]: r["value"] for r in client.get("/api/v1/settings").json()}[key]
    assert after == before


def test_settings_list_marks_which_values_are_defaults(client):
    key = "recruitment.negotiation.slots_offered"
    rows = {r["key"]: r for r in client.get("/api/v1/settings").json()}
    if rows[key]["is_default"]:
        assert rows[key]["value"] == get_definition(key).default
    assert client.put(f"/api/v1/settings/{key}", json={"value": 5}).status_code == 200
    rows = {r["key"]: r for r in client.get("/api/v1/settings").json()}
    assert rows[key]["value"] == 5 and rows[key]["is_default"] is False


def test_resolve_reports_the_scope_the_value_came_from(db_session):
    ctx = SettingContext(tenant=_tenant_ctx())
    service = SettingsService(db_session)
    register(SettingDef("test.resolve_source", "int", 7, module="test"), replace=True)
    assert service.resolve("test.resolve_source", ctx) == (7, None)
    service.set("test.resolve_source", 9, scope_type="tenant", scope_id=None, actor="a@example.com", tenant=_tenant_ctx())
    assert service.resolve("test.resolve_source", ctx) == (9, "tenant")


# --- Part 31: import is all or nothing; revert matches the scope id too ---


def test_import_with_one_bad_value_saves_nothing(client):
    key = "recruitment.negotiation.slots_offered"
    before = {r["key"]: r["value"] for r in client.get("/api/v1/settings").json()}[key]
    r = client.post("/api/v1/settings/import", json={"settings": {key: (before or 3) + 1, "recruitment.scoring.shortlist_threshold": 500}})
    assert r.status_code == 400 and "shortlist_threshold" in r.json()["detail"] and "Nothing was imported" in r.json()["detail"]
    assert {r["key"]: r["value"] for r in client.get("/api/v1/settings").json()}[key] == before

    r = client.post("/api/v1/settings/import", json={"settings": {key: 4, "no.such.setting": 1}})
    assert r.status_code == 200 and r.json()["imported"] == [key] and r.json()["skipped"][0]["key"] == "no.such.setting"


def test_revert_picks_the_version_of_the_same_scope_id(client, db_session):
    """Two users' rows of the same setting both have a version 1; reverting user A's v1 must not take user B's value."""
    import uuid as _uuid

    key = "test.revert_scope"
    register(SettingDef(key, "int", 0, module="test", scopes_allowed=("tenant", "user")), replace=True)
    service = SettingsService(db_session)
    user_a, user_b = _uuid.uuid4(), _uuid.uuid4()
    service.set(key, 11, scope_type="user", scope_id=user_b, actor="b@example.com", tenant=_tenant_ctx())  # B v1 = 11 (newest first in history)
    service.set(key, 22, scope_type="user", scope_id=user_a, actor="a@example.com", tenant=_tenant_ctx())  # A v1 = 22
    service.set(key, 23, scope_type="user", scope_id=user_a, actor="a@example.com", tenant=_tenant_ctx())  # A v2 = 23
    r = client.post(f"/api/v1/settings/{key}/revert", json={"version": 1, "scope_type": "user", "scope_id": str(user_a)})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 22 and r.json()["scope_id"] == str(user_a)
    assert client.post(f"/api/v1/settings/{key}/revert", json={"version": 9, "scope_type": "user", "scope_id": str(user_a)}).status_code == 404
