"""Settings Registry (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4): every module declares
the tunable values it owns as a SettingDef, once, in its own settings.py (per section E's
package layout) -- `register()` here. The registry itself never stores VALUES (that's
setting_values, a tenant table -- see resolver.py); it's purely the schema: what keys exist,
what type/default/scopes each one allows, and where its label/help text comes from.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Layered resolution order (section D) -- first non-null wins. Most of these scope types
# (position, department, location, business_unit, legal_entity) don't have a real backing
# entity yet (Part 7 creates Core HR's org model) -- the resolver still walks this exact
# chain regardless, it just never finds a setting_values row for a scope type nothing has
# ever been scoped to, and falls through to the next one. Nothing about the resolution
# mechanism itself depends on those entities existing.
SCOPE_ORDER = (
    "user", "position", "department", "location", "business_unit",
    "legal_entity", "tenant", "plan", "platform",
)

SETTING_TYPES = (
    "str", "int", "decimal", "bool", "enum", "json", "duration", "time", "color",
    "email", "url", "secret_ref", "connection_ref", "template_ref", "master_ref",
)


@dataclass(frozen=True)
class SettingDef:
    key: str  # dotted, e.g. "recruitment.negotiation.slots_offered"
    type: str
    default: Any
    module: str  # which module owns this (e.g. "recruitment", "org", "ai")
    group: str = ""
    label_i18n_key: str = ""
    help_i18n_key: str = ""
    json_schema: Optional[dict] = None
    scopes_allowed: tuple = ("tenant",)  # subset of SCOPE_ORDER a value may be set at
    sensitive: bool = False
    requires_restart: bool = False
    validators: tuple[Callable[[Any], None], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.type not in SETTING_TYPES:
            raise ValueError(f"{self.key}: unknown setting type {self.type!r}")
        for scope in self.scopes_allowed:
            if scope not in SCOPE_ORDER:
                raise ValueError(f"{self.key}: unknown scope {scope!r}")

    def validate(self, value: Any) -> None:
        """Raises ValueError when `value` can't be stored for this setting: wrong type for
        `type`, outside `json_schema` (the subset in use: type / enum / minimum / maximum /
        minLength / maxLength / items / minItems / maxItems), or rejected by a custom validator.
        None is accepted only for settings whose default is None."""
        if value is None:
            if self.default is None:
                return
            raise ValueError(f"{self.key}: a value is required")
        _check_type(self.key, self.type, value)
        if self.json_schema:
            _check_schema(self.key, value, self.json_schema)
        for validator in self.validators:
            validator(value)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STRING_TYPES = ("str", "enum", "email", "url", "color")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(value)


def _check_type(key: str, setting_type: str, value: Any) -> None:
    if setting_type == "int" and not _is_int(value):
        raise ValueError(f"{key}: must be a whole number")
    if setting_type == "decimal" and not _is_number(value):
        raise ValueError(f"{key}: must be a number")
    if setting_type == "bool" and not isinstance(value, bool):
        raise ValueError(f"{key}: must be true or false")
    if setting_type in _STRING_TYPES and not isinstance(value, str):
        raise ValueError(f"{key}: must be text")
    if setting_type == "email" and value and not _EMAIL_RE.match(value):
        raise ValueError(f"{key}: must be an email address")
    # json / duration / time / *_ref: no fixed Python shape -- json_schema (if any) decides.


_SCHEMA_TYPES = {
    "integer": _is_int,
    "number": _is_number,
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _check_schema(where: str, value: Any, schema: dict) -> None:
    expected = schema.get("type")
    if expected in _SCHEMA_TYPES and not _SCHEMA_TYPES[expected](value):
        raise ValueError(f"{where}: must be of type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: must be one of {', '.join(repr(v) for v in schema['enum'])}")
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{where}: must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{where}: must be at most {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValueError(f"{where}: must be at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ValueError(f"{where}: must be at most {schema['maxLength']} characters")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValueError(f"{where}: needs at least {schema['minItems']} entries")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{where}: allows at most {schema['maxItems']} entries")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                _check_schema(f"{where}[{i}]", item, schema["items"])


class SettingAlreadyRegisteredError(Exception):
    pass


class UnknownSettingError(Exception):
    pass


_REGISTRY: dict[str, SettingDef] = {}


def register(setting_def: SettingDef, *, replace: bool = False) -> None:
    """`replace=True` only for test fixtures that need to re-register the same key across
    independent test runs sharing one process -- real module settings.py files register
    exactly once, at import time, and a genuine duplicate key is a bug worth catching."""
    if not replace and setting_def.key in _REGISTRY:
        raise SettingAlreadyRegisteredError(setting_def.key)
    _REGISTRY[setting_def.key] = setting_def


def get_definition(key: str) -> SettingDef:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownSettingError(key) from None


def all_definitions(module: Optional[str] = None) -> list[SettingDef]:
    defs = list(_REGISTRY.values())
    if module is not None:
        defs = [d for d in defs if d.module == module]
    return sorted(defs, key=lambda d: d.key)


def is_registered(key: str) -> bool:
    return key in _REGISTRY
