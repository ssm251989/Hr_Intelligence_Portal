"""TenantOwned mixin (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2 + section B): every
tenant-owned table gets tenant_id UUID NOT NULL -- even in dedicated_db isolation mode, per
section B ("enables RLS mode, safe export/import, and defence-in-depth") -- auto-populated
on insert from the current TenantContext, and auto-filtered on every ORM read. Postgres Row
Level Security (see the enable_rls() helper Part 2's tenant migration calls for every
TenantOwned table) is the mechanism that actually protects a raw/non-ORM query too; this
mixin's own read-side filter is an app-layer belt-and-suspenders, not the sole guarantee.
"""

from sqlalchemy import Column, event
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session as OrmSession, declared_attr, with_loader_criteria

from app.platform.tenancy.context import get_current_tenant


class TenantOwned:
    @declared_attr
    def tenant_id(cls):
        return Column(PGUUID(as_uuid=True), nullable=False, index=True)


def _populate_tenant_id(mapper, connection, target) -> None:
    if getattr(target, "tenant_id", None) is not None:
        return
    ctx = get_current_tenant()
    if ctx is not None:
        target.tenant_id = ctx.tenant_id


_insert_hook_installed_for: set = set()


def register_tenant_owned_events(base) -> None:
    """Call once, after every TenantOwned model has been imported (registered on `base`'s
    metadata) -- e.g. right after `import app.models`. Idempotent per class, so it's safe to
    call again if more models get imported later (or from both app startup and test
    conftest without double-registering the same class)."""
    for mapper_ in base.registry.mappers:
        cls = mapper_.class_
        if issubclass(cls, TenantOwned) and cls not in _insert_hook_installed_for:
            event.listen(cls, "before_insert", _populate_tenant_id, propagate=True)
            _insert_hook_installed_for.add(cls)


def _tenant_read_filter(execute_state) -> None:
    if not execute_state.is_select:
        return
    ctx = get_current_tenant()
    if ctx is None:
        return
    # `tenant_id` (a plain UUID), not `ctx` (an arbitrary dataclass instance), as the
    # lambda's closure variable -- with_loader_criteria's caching needs a closure variable
    # it can treat as a literal bound value, which a whole TenantContext object isn't.
    tenant_id = ctx.tenant_id
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(TenantOwned, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
    )


_read_filter_installed = False


def install_tenant_read_filter() -> None:
    """Registers the global do_orm_execute filter once per process. Only affects queries
    against TenantOwned subclasses (control-plane models never are) -- safe to leave
    installed even for a Session that also touches the control-plane database."""
    global _read_filter_installed
    if _read_filter_installed:
        return
    event.listen(OrmSession, "do_orm_execute", _tenant_read_filter)
    _read_filter_installed = True
