"""Custom fields (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 1): tenant-defined fields on
top of a real entity's own `custom_fields JSONB` column. Validation is a plain Python
function checking each active def's `type`/`validation_json` against a submitted payload
(rather than dynamically generating a real pydantic model class per request, which section
1's own wording suggests but which buys nothing here -- the check logic is identical
either way, and a hand-written validator is far easier to read/test/extend). Field-level
security from Part 5 (`platform.iam.field_security`) applies here unchanged: a custom
field's `code` IS its `field` name for `field_security` purposes, `entity` matches exactly.
"""

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.metadata import CustomFieldDef, ENTITIES_WITH_CUSTOM_FIELD_STORAGE
from app.platform.tenancy.context import TenantContext


class CustomFieldValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(f"Custom field validation failed: {errors}")


class EntityStorageNotAvailableError(Exception):
    pass


def active_defs(db: Session, tenant: TenantContext, entity: str) -> list[CustomFieldDef]:
    return (
        db.query(CustomFieldDef)
        .filter(CustomFieldDef.tenant_id == tenant.tenant_id, CustomFieldDef.entity == entity, CustomFieldDef.is_active.is_(True))
        .order_by(CustomFieldDef.section, CustomFieldDef.order)
        .all()
    )


def _type_error(field_def: CustomFieldDef, value: Any) -> Optional[str]:
    t = field_def.type
    if t in ("text", "longtext", "email", "phone", "url", "picklist", "user", "employee", "lookup"):
        return None if isinstance(value, str) else "must be a string"
    if t == "multipicklist":
        return None if isinstance(value, list) and all(isinstance(v, str) for v in value) else "must be a list of strings"
    if t in ("number", "decimal", "currency"):
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "must be a number"
    if t == "bool":
        return None if isinstance(value, bool) else "must be true/false"
    if t in ("date", "datetime"):
        if isinstance(value, (date, datetime)):
            return None
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value)
                return None
            except ValueError:
                return "must be an ISO date/datetime string"
        return "must be an ISO date/datetime string"
    if t == "formula":
        return "formula fields are computed, not submitted"  # never a valid submission target
    if t == "file":
        return None if isinstance(value, str) else "must be a file reference (string)"
    return None


def _validation_json_errors(field_def: CustomFieldDef, value: Any) -> Optional[str]:
    rules = field_def.validation_json or {}
    if field_def.type == "picklist" and "options" in rules and value not in rules["options"]:
        return f"must be one of {rules['options']}"
    if field_def.type == "multipicklist" and "options" in rules:
        invalid = [v for v in value if v not in rules["options"]]
        if invalid:
            return f"invalid option(s): {invalid}"
    if field_def.type in ("number", "decimal", "currency"):
        if "min" in rules and value < rules["min"]:
            return f"must be >= {rules['min']}"
        if "max" in rules and value > rules["max"]:
            return f"must be <= {rules['max']}"
    if field_def.type in ("text", "longtext") and "pattern" in rules:
        import re

        if not re.match(rules["pattern"], value):
            return "does not match the required pattern"
    return None


def validate_custom_fields(db: Session, tenant: TenantContext, entity: str, payload: dict, *, row_context: Optional[dict] = None) -> dict:
    """`payload` is ONLY custom-field values being submitted (keyed by def `code`) -- a
    key that isn't a defined custom field for this entity is rejected as unknown, never
    silently ignored. `row_context` is everything ELSE a required/visible_condition_
    jsonlogic expression might reference (the row's own standard columns, other already-
    saved custom field values, ...) -- never itself validated against a def, only read.

    Returns the validated (and type-coerced-nothing, stored as-submitted) dict to
    persist. Raises CustomFieldValidationError({code: message}) -- never partial-applies a
    payload with some fields valid and others silently dropped."""
    from json_logic import jsonLogic

    defs_by_code = {d.code: d for d in active_defs(db, tenant, entity)}
    context = {**(row_context or {}), **payload}
    errors: dict[str, str] = {}
    result: dict[str, Any] = {}

    for code, field_def in defs_by_code.items():
        required = bool(field_def.required_condition_jsonlogic and jsonLogic(field_def.required_condition_jsonlogic, context))
        visible = field_def.visible_condition_jsonlogic is None or jsonLogic(field_def.visible_condition_jsonlogic, context)
        if code not in payload or payload[code] is None:
            if required and visible:
                errors[code] = "is required"
            elif field_def.default is not None:
                result[code] = field_def.default
            continue
        value = payload[code]
        type_error = _type_error(field_def, value)
        if type_error:
            errors[code] = type_error
            continue
        rule_error = _validation_json_errors(field_def, value)
        if rule_error:
            errors[code] = rule_error
            continue
        result[code] = value

    unknown = set(payload) - set(defs_by_code)
    for code in unknown:
        errors[code] = "is not a defined custom field for this entity"

    if errors:
        raise CustomFieldValidationError(errors)
    return result


def require_storage(entity: str) -> None:
    if entity not in ENTITIES_WITH_CUSTOM_FIELD_STORAGE:
        raise EntityStorageNotAvailableError(
            f"entity={entity!r} has no custom_fields storage column yet (belongs to a future part's table) -- "
            "a def can still be authored, just not attached to a real row today."
        )
