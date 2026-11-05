"""TenantEngineRegistry (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 2): an LRU cache of
SQLAlchemy engines keyed by tenant_id, DSN pulled from the control-plane SecretStore (never
a plaintext column) via each tenant's own `db_dsn_secret_ref`. Under TENANCY_MODE=single
there is exactly one tenant and this registry holds exactly one cached engine -- the
multi-tenant fan-out this exists for is TENANCY_MODE=multi (kept in the code, not deployed
at launch, per section B).
"""

from collections import OrderedDict
from typing import Optional
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.platform.secrets.store import get_secret_store
from app.platform.tenancy.models_cp import ControlPlaneSecret, ControlPlaneSecretScope, Tenant

CONTROL_PLANE_SECRET_SCOPE = "control_plane"

# Platform default (section A: "platform defaults that are generic and overridable" are
# allowed in code) -- becomes the real setting platform.db.pool_size once a tenant DB is
# reachable to read Settings Registry values FROM in the first place (the registry that
# creates that very engine can't yet query through it for its own pool size).
DEFAULT_POOL_SIZE = 5


class TenantEngineRegistry:
    def __init__(self, control_plane_db_factory, max_cached_engines: int = 64):
        """`control_plane_db_factory` is a zero-arg callable returning a fresh control-plane
        Session (e.g. platform.tenancy.database_cp.ControlPlaneSessionLocal) -- each DSN
        lookup opens and closes its own short-lived session rather than holding one open for
        the registry's lifetime."""
        self._control_plane_db_factory = control_plane_db_factory
        self._max_cached_engines = max_cached_engines
        self._engines: "OrderedDict[UUID, Engine]" = OrderedDict()

    def _resolve_dsn(self, tenant: Tenant) -> str:
        if not tenant.db_dsn_secret_ref:
            raise ValueError(f"Tenant {tenant.slug} has no db_dsn_secret_ref set yet (still provisioning?)")
        db = self._control_plane_db_factory()
        try:
            store = get_secret_store(db, ControlPlaneSecret, ControlPlaneSecretScope, CONTROL_PLANE_SECRET_SCOPE)
            return store.get(tenant.db_dsn_secret_ref)
        finally:
            db.close()

    def get_engine(self, tenant: Tenant) -> Engine:
        cached = self._engines.get(tenant.id)
        if cached is not None:
            self._engines.move_to_end(tenant.id)
            return cached

        dsn = self._resolve_dsn(tenant)
        engine = create_engine(dsn, pool_size=DEFAULT_POOL_SIZE)
        self._engines[tenant.id] = engine
        self._engines.move_to_end(tenant.id)
        if len(self._engines) > self._max_cached_engines:
            _evicted_tenant_id, evicted_engine = self._engines.popitem(last=False)
            evicted_engine.dispose()
        return engine

    def session_for(self, tenant: Tenant) -> Session:
        from sqlalchemy.orm import sessionmaker

        engine = self.get_engine(tenant)
        return sessionmaker(bind=engine)()

    def evict(self, tenant_id: UUID) -> None:
        engine = self._engines.pop(tenant_id, None)
        if engine is not None:
            engine.dispose()

    def cached_tenant_ids(self) -> list:
        return list(self._engines.keys())
