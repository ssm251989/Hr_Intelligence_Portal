"""SettingsService (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4) -- the resolver that
walks SCOPE_ORDER and returns the first non-null value, backed by setting_values/
setting_value_history (app/models/setting_value.py).

Caching: the spec calls for a Redis cache + pub/sub invalidation (`t:{tid}:settings`).
This installation has no Redis instance provisioned yet (see docs/build_log.md's own
decision note) -- an in-process dict cache, keyed by (tenant_id, key, scope_type,
scope_id) and invalidated synchronously on every write via _invalidate(), stands in for it.
Multi-process/multi-worker deployments won't see each other's writes reflected until Part
13 actually wires up Redis pub/sub; single dev-process and single-worker deployments (this
app's current shape) are unaffected.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.setting_value import SettingValue, SettingValueHistory
from app.platform.settings.registry import SCOPE_ORDER, get_definition
from app.platform.tenancy.context import TenantContext


@dataclass(frozen=True)
class SettingContext:
    """What SettingsService.get/get_many/set need to resolve/scope a value -- deliberately
    NOT the same object as TenantContext, since a setting lookup also needs to know WHICH
    user/position/department/... is asking, none of which TenantContext itself carries.
    scope_ids maps a scope_type (from SCOPE_ORDER) to the id relevant to this request, for
    every scope this caller actually has one for -- e.g. {"user": user.id}. A scope this
    dict has no entry for is simply skipped during resolution, same as one that has an
    entry but no matching setting_values row."""

    tenant: TenantContext
    scope_ids: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.scope_ids is None:
            object.__setattr__(self, "scope_ids", {})


class SettingNotSetError(Exception):
    """Raised by get() only when the key has no registry default AND nothing resolved --
    a registry bug (every real SettingDef has a default), never a normal runtime path."""


# Caches the plain resolved value (or the sentinel below for "no row"), never the
# SettingValue ORM instance itself -- an instance is bound to the Session that loaded it
# and goes unusable (DetachedInstanceError) the moment that session closes, which a
# module-level cache surviving across many short-lived sessions (every request's own
# get_db() session, every test's own db_session) hits constantly. Found the hard way: a
# value cached by one test's session raised DetachedInstanceError when a LATER test (a
# fresh session) read it back from cache.
_NO_VALUE = object()
_cache: dict[tuple, Any] = {}


def _cache_key(tenant_id: UUID, key: str, scope_type: str, scope_id: Optional[UUID]) -> tuple:
    return (tenant_id, key, scope_type, scope_id)


def _invalidate(tenant_id: UUID, key: str) -> None:
    for cache_key in [k for k in _cache if k[0] == tenant_id and k[1] == key]:
        del _cache[cache_key]


def clear_all_cache() -> None:
    """For tests only -- production invalidates surgically via _invalidate() on write."""
    _cache.clear()


class SettingsService:
    def __init__(self, db: Session):
        self.db = db

    def _get_value(self, tenant_id: UUID, key: str, scope_type: str, scope_id: Optional[UUID]):
        """Returns the resolved value_json for this exact scope, or _NO_VALUE if no row
        matches -- never the ORM row itself, see _cache's own comment on why."""
        cache_key = _cache_key(tenant_id, key, scope_type, scope_id)
        if cache_key in _cache:
            return _cache[cache_key]
        query = self.db.query(SettingValue.value_json).filter(
            SettingValue.tenant_id == tenant_id, SettingValue.key == key, SettingValue.scope_type == scope_type,
        )
        query = query.filter(SettingValue.scope_id == scope_id) if scope_id is not None else query.filter(SettingValue.scope_id.is_(None))
        row = query.first()
        value = row[0] if row is not None else _NO_VALUE
        _cache[cache_key] = value
        return value

    def get(self, key: str, ctx: SettingContext) -> Any:
        setting_def = get_definition(key)
        for scope_type in SCOPE_ORDER:
            if scope_type == "platform":
                return setting_def.default
            if scope_type == "plan":
                # No plan-limits/plan-default source exists yet (Part 13) -- falls through
                # to platform default, same as any other scope with nothing set for it.
                continue
            if scope_type == "tenant":
                value = self._get_value(ctx.tenant.tenant_id, key, "tenant", None)
            else:
                scope_id = ctx.scope_ids.get(scope_type)
                if scope_id is None:
                    continue
                value = self._get_value(ctx.tenant.tenant_id, key, scope_type, scope_id)
            if value is not _NO_VALUE:
                return value
        return setting_def.default

    def get_many(self, prefix: str, ctx: SettingContext) -> dict:
        from app.platform.settings.registry import all_definitions

        return {d.key: self.get(d.key, ctx) for d in all_definitions() if d.key.startswith(prefix)}

    def set(
        self, key: str, value: Any, *, scope_type: str, scope_id: Optional[UUID], actor: str, tenant: TenantContext,
    ) -> SettingValue:
        setting_def = get_definition(key)
        if scope_type not in setting_def.scopes_allowed:
            raise ValueError(f"{key} may not be set at scope {scope_type!r} (allowed: {setting_def.scopes_allowed})")
        setting_def.validate(value)

        query = self.db.query(SettingValue).filter(
            SettingValue.tenant_id == tenant.tenant_id, SettingValue.key == key, SettingValue.scope_type == scope_type,
        )
        query = query.filter(SettingValue.scope_id == scope_id) if scope_id is not None else query.filter(SettingValue.scope_id.is_(None))
        row = query.first()

        if row is None:
            row = SettingValue(
                tenant_id=tenant.tenant_id, key=key, scope_type=scope_type, scope_id=scope_id,
                value_json=value, version=1, updated_by=actor,
            )
            self.db.add(row)
        else:
            row.value_json = value
            row.version += 1
            row.updated_by = actor

        self.db.flush()
        self.db.add(SettingValueHistory(
            tenant_id=tenant.tenant_id, key=key, scope_type=scope_type, scope_id=scope_id,
            value_json=value, version=row.version, updated_by=actor,
            # Explicit Python wall-clock time, not the column's server_default=now() --
            # Postgres now() is pinned to the enclosing transaction's start time, so two
            # history rows written moments apart in the SAME transaction would otherwise get
            # an IDENTICAL updated_at, breaking history()'s "most recent first" ordering
            # (same reasoning app.interview_scheduling.negotiation._create_negotiation_row
            # already established for this exact class of bug).
            updated_at=datetime.now(timezone.utc),
        ))
        self.db.commit()
        self.db.refresh(row)
        _invalidate(tenant.tenant_id, key)
        return row

    def history(self, key: str, ctx: SettingContext) -> list[SettingValueHistory]:
        return (
            self.db.query(SettingValueHistory)
            .filter(SettingValueHistory.tenant_id == ctx.tenant.tenant_id, SettingValueHistory.key == key)
            .order_by(SettingValueHistory.updated_at.desc())
            .all()
        )
