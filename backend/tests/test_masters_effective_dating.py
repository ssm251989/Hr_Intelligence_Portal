"""platform/metadata/masters.py -- effective-dating, is_active filtering (Part 6
CHECKS)."""

from datetime import datetime, timedelta, timezone

from app.models.metadata import MasterType
from app.platform.metadata.masters import MASTER_TYPES, create_value, deactivate_value, list_values, register_master_types
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_register_master_types_seeds_every_spec_type(db_session):
    register_master_types(db_session)
    codes = {t.code for t in db_session.query(MasterType).all()}
    assert codes == {code for code, _, _ in MASTER_TYPES}


def test_register_master_types_is_idempotent(db_session):
    register_master_types(db_session)
    register_master_types(db_session)
    assert db_session.query(MasterType).filter(MasterType.code == "skill").count() == 1


def test_country_state_city_are_marked_hierarchical(db_session):
    register_master_types(db_session)
    for code in ("country", "state", "city"):
        assert db_session.get(MasterType, code).hierarchical is True
    assert db_session.get(MasterType, "skill").hierarchical is False


def test_create_and_list_values(db_session):
    # "test_"-prefixed codes -- hrctl.seed_masters has already seeded real "linkedin"/
    # "referral"-shaped codes into this same tenant's real, committed data, so a fixture
    # using an unprefixed code here would collide with that real row under source_of_
    # hire's own tenant+type_code+code UNIQUE constraint.
    register_master_types(db_session)
    create_value(db_session, TENANT, type_code="source_of_hire", code="test_linkedin", label_i18n={"en": "LinkedIn"})
    create_value(db_session, TENANT, type_code="source_of_hire", code="test_referral", label_i18n={"en": "Employee Referral"})

    values = list_values(db_session, TENANT, "source_of_hire")
    codes = {v.code for v in values}
    assert {"test_linkedin", "test_referral"} <= codes


def test_deactivate_value_excludes_it_from_the_default_listing(db_session):
    register_master_types(db_session)
    value = create_value(db_session, TENANT, type_code="rejection_reason", code="salary_mismatch", label_i18n={"en": "Salary Mismatch"})

    deactivate_value(db_session, TENANT, value.id)

    assert value.code not in {v.code for v in list_values(db_session, TENANT, "rejection_reason")}
    # but still visible when explicitly including inactive
    assert value.code in {v.code for v in list_values(db_session, TENANT, "rejection_reason", include_inactive=True)}


def test_effective_dating_excludes_a_not_yet_started_value(db_session):
    register_master_types(db_session)
    future = datetime.now(timezone.utc) + timedelta(days=30)
    create_value(db_session, TENANT, type_code="grade", code="G10", label_i18n={"en": "Grade 10"}, effective_from=future)

    assert "G10" not in {v.code for v in list_values(db_session, TENANT, "grade")}


def test_effective_dating_excludes_an_expired_value(db_session):
    register_master_types(db_session)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    create_value(db_session, TENANT, type_code="grade", code="G1", label_i18n={"en": "Grade 1 (retired)"}, effective_to=past)

    assert "G1" not in {v.code for v in list_values(db_session, TENANT, "grade")}


def test_effective_dating_includes_a_currently_active_value(db_session):
    register_master_types(db_session)
    now = datetime.now(timezone.utc)
    create_value(
        db_session, TENANT, type_code="grade", code="G5", label_i18n={"en": "Grade 5"},
        effective_from=now - timedelta(days=1), effective_to=now + timedelta(days=1),
    )

    assert "G5" in {v.code for v in list_values(db_session, TENANT, "grade")}


def test_master_values_are_scoped_hierarchically_via_parent_id(db_session):
    register_master_types(db_session)
    country = create_value(db_session, TENANT, type_code="country", code="IN", label_i18n={"en": "India"})
    state = create_value(db_session, TENANT, type_code="state", code="KA", label_i18n={"en": "Karnataka"}, parent_id=country.id)

    assert state.parent_id == country.id
