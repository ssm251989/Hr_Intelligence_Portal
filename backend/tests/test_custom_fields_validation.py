"""platform/metadata/custom_fields.py (Part 6 CHECKS)."""

import uuid

import pytest

from app.models.metadata import CustomFieldDef
from app.platform.metadata.custom_fields import (
    CustomFieldValidationError,
    EntityStorageNotAvailableError,
    active_defs,
    require_storage,
    validate_custom_fields,
)
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_def(db_session, entity="candidate", code="favorite_color", type_="text", **kwargs) -> CustomFieldDef:
    row = CustomFieldDef(tenant_id=TENANT_1_ID, entity=entity, code=code, type=type_, label_i18n={"en": code}, **kwargs)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_active_defs_excludes_inactive(db_session):
    _make_def(db_session, code="a")
    _make_def(db_session, code="b", is_active=False)
    codes = {d.code for d in active_defs(db_session, TENANT, "candidate")}
    assert codes == {"a"}


def test_validate_accepts_a_correct_text_value(db_session):
    _make_def(db_session, code="favorite_color", type_="text")
    result = validate_custom_fields(db_session, TENANT, "candidate", {"favorite_color": "blue"})
    assert result == {"favorite_color": "blue"}


def test_validate_rejects_wrong_type(db_session):
    _make_def(db_session, code="age", type_="number")
    with pytest.raises(CustomFieldValidationError) as exc_info:
        validate_custom_fields(db_session, TENANT, "candidate", {"age": "not-a-number"})
    assert "age" in exc_info.value.errors


def test_validate_rejects_unknown_field_code(db_session):
    with pytest.raises(CustomFieldValidationError) as exc_info:
        validate_custom_fields(db_session, TENANT, "candidate", {"nonexistent_field": "x"})
    assert "nonexistent_field" in exc_info.value.errors


def test_validate_enforces_picklist_options(db_session):
    _make_def(db_session, code="shirt_size", type_="picklist", validation_json={"options": ["S", "M", "L"]})
    validate_custom_fields(db_session, TENANT, "candidate", {"shirt_size": "M"})  # does not raise
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields(db_session, TENANT, "candidate", {"shirt_size": "XXL"})


def test_validate_enforces_number_min_max(db_session):
    _make_def(db_session, code="score", type_="number", validation_json={"min": 0, "max": 100})
    validate_custom_fields(db_session, TENANT, "candidate", {"score": 50})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields(db_session, TENANT, "candidate", {"score": 150})


def test_validate_required_condition_jsonlogic(db_session):
    """`needs_visa` here represents a standard (non-custom-field) column on the row --
    supplied via `row_context`, never `payload` (payload is ONLY the custom_fields values
    being submitted; a key in payload that isn't a defined custom field code is rejected
    as unknown, exercised separately by test_validate_rejects_unknown_field_code)."""
    _make_def(db_session, code="visa_number", type_="text", required_condition_jsonlogic={"==": [{"var": "needs_visa"}, True]})
    with pytest.raises(CustomFieldValidationError) as exc_info:
        validate_custom_fields(db_session, TENANT, "candidate", {}, row_context={"needs_visa": True})
    assert "visa_number" in exc_info.value.errors
    # not required when the condition doesn't hold
    result = validate_custom_fields(db_session, TENANT, "candidate", {}, row_context={"needs_visa": False})
    assert "visa_number" not in result


def test_validate_applies_default_when_omitted(db_session):
    _make_def(db_session, code="tier", type_="text", default="bronze")
    result = validate_custom_fields(db_session, TENANT, "candidate", {})
    assert result["tier"] == "bronze"


def test_validate_bool_and_multipicklist(db_session):
    _make_def(db_session, code="remote_ok", type_="bool")
    _make_def(db_session, code="languages", type_="multipicklist", validation_json={"options": ["en", "hi", "ta"]})
    result = validate_custom_fields(db_session, TENANT, "candidate", {"remote_ok": True, "languages": ["en", "hi"]})
    assert result == {"remote_ok": True, "languages": ["en", "hi"]}
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields(db_session, TENANT, "candidate", {"languages": ["fr"]})


def test_require_storage_raises_for_entities_with_no_real_table_yet(db_session):
    require_storage("candidate")  # does not raise
    with pytest.raises(EntityStorageNotAvailableError):
        require_storage("employee")
