"""platform/i18n/service.py (Part 6 CHECKS)."""

from app.models.metadata import I18nOverride
from app.platform.i18n import service as i18n_service
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def test_base_bundle_has_the_seeded_nav_keys():
    bundle = i18n_service.base_bundle("en")
    assert bundle["nav.jobs"] == "Jobs"
    assert bundle["entity.employee"] == "Employee"


def test_base_bundle_falls_back_to_english_for_an_unsupported_locale():
    assert i18n_service.base_bundle("fr") == i18n_service.base_bundle("en")


def test_translate_returns_the_base_bundle_value_with_no_override(db_session):
    assert i18n_service.translate(db_session, TENANT, "en", "nav.jobs") == "Jobs"


def test_translate_prefers_a_tenant_override(db_session):
    i18n_service.set_override(db_session, TENANT, "en", "entity.employee", "Associate")
    assert i18n_service.translate(db_session, TENANT, "en", "entity.employee") == "Associate"
    # base bundle for the SAME key in a different locale is unaffected
    assert i18n_service.translate(db_session, TENANT, "hi", "entity.employee") == "कर्मचारी"


def test_translate_falls_back_to_default_then_key_for_an_unknown_key(db_session):
    assert i18n_service.translate(db_session, TENANT, "en", "totally.unknown.key") == "totally.unknown.key"
    assert i18n_service.translate(db_session, TENANT, "en", "totally.unknown.key", default="Fallback") == "Fallback"


def test_merged_bundle_layers_overrides_on_top_of_the_base_bundle(db_session):
    i18n_service.set_override(db_session, TENANT, "hi", "entity.requisition", "MRF")
    merged = i18n_service.merged_bundle(db_session, TENANT, "hi")
    assert merged["entity.requisition"] == "MRF"
    assert merged["nav.jobs"] == "नौकरियां"  # unaffected keys still come from the base bundle


def test_set_override_upserts_rather_than_duplicating(db_session):
    i18n_service.set_override(db_session, TENANT, "en", "nav.jobs", "Openings")
    i18n_service.set_override(db_session, TENANT, "en", "nav.jobs", "Vacancies")
    rows = db_session.query(I18nOverride).filter(I18nOverride.tenant_id == TENANT_1_ID, I18nOverride.locale == "en", I18nOverride.key == "nav.jobs").all()
    assert len(rows) == 1
    assert rows[0].value == "Vacancies"


def test_delete_override_reverts_to_the_base_bundle_value(db_session):
    i18n_service.set_override(db_session, TENANT, "en", "nav.jobs", "Openings")
    row = db_session.query(I18nOverride).filter(I18nOverride.tenant_id == TENANT_1_ID, I18nOverride.locale == "en", I18nOverride.key == "nav.jobs").one()

    i18n_service.delete_override(db_session, TENANT, row.id)

    assert i18n_service.translate(db_session, TENANT, "en", "nav.jobs") == "Jobs"
