"""Provider catalog (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- every adapter module
in platform/connectors/providers/ calls register_provider() once, at import time. Each
adapter class implements `test_connection()` / `health_check()` (both return
capabilities.ProviderResult) plus whichever capability methods its CAPABILITIES declare.
"""

from dataclasses import dataclass
from typing import Optional


class NotYetImplementedProviderError(Exception):
    """Raised by a "Later" (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) provider's
    test_connection/health_check/every capability method -- registered in the catalog
    (so it appears in GET /api/v1/connectors/providers and its config schema is real) but
    genuinely not implemented: no adapter class, no live service to test against yet."""


@dataclass(frozen=True)
class ProviderSpec:
    code: str
    capabilities: tuple[str, ...]
    config_schema: dict
    secret_fields: tuple[str, ...] = ()
    oauth: Optional[dict] = None  # {"auth_url":..., "token_url":..., "scopes":[...]}
    adapter_cls: Optional[type] = None  # None => a "Later" provider, not yet implemented
    rate_limit_default: Optional[dict] = None


_PROVIDERS: dict[str, ProviderSpec] = {}


def register_provider(spec: ProviderSpec, *, replace: bool = False) -> None:
    if not replace and spec.code in _PROVIDERS:
        raise ValueError(f"Provider already registered: {spec.code}")
    _PROVIDERS[spec.code] = spec


def get_provider(code: str) -> ProviderSpec:
    try:
        return _PROVIDERS[code]
    except KeyError:
        raise KeyError(f"Unknown provider: {code}") from None


def all_providers() -> list[ProviderSpec]:
    return sorted(_PROVIDERS.values(), key=lambda p: p.code)


def is_registered(code: str) -> bool:
    return code in _PROVIDERS
