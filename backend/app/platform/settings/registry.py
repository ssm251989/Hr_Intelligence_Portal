"""Settings Registry (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4): every module declares
the tunable values it owns as a SettingDef, once, in its own settings.py (per section E's
package layout) -- `register()` here. The registry itself never stores VALUES (that's
setting_values, a tenant table -- see resolver.py); it's purely the schema: what keys exist,
what type/default/scopes each one allows, and where its label/help text comes from.
"""

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
        for validator in self.validators:
            validator(value)


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
