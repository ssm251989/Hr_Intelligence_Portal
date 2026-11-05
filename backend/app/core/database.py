from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.orm import Session as OrmSession

from app.core.config import settings

engine = create_engine(settings.APP_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@event.listens_for(OrmSession, "after_begin")
def _set_tenant_id_for_rls(session, transaction, connection) -> None:
    """Part 2 (docs/HRMS_COMPLETE_SPEC.txt): SET LOCAL app.tenant_id = <current
    TenantContext>, re-applied at the start of EVERY transaction ANY ORM Session opens (not
    just its first, and not just SessionLocal's own -- registered on the base Session class,
    same as platform.tenancy.mixins's read-filter event, so tests' own separately-
    constructed sessionmaker bound to the same engine gets this too) -- exactly the "per
    transaction" the spec calls for, and safe against connection-pool reuse leaking one
    tenant's setting into a later session's first transaction, unlike a plain (non-LOCAL)
    SET applied once at session creation would be. Fires for a raw SessionLocal() call
    outside of get_db() below too (app/local_import/scheduler.py's background job) -- as
    long as a TenantContext is active (contextvars, not a session attribute) when that
    transaction begins; see platform.tenancy.context.tenant_context for how the scheduler
    supplies one itself, since it has no request to inherit one from. A control-plane
    session's transaction harmlessly sets the same value too -- no tenant table there for
    any RLS policy to apply to.

    This is what actually makes every tenant table's RLS policy
    (`USING (tenant_id = current_setting('app.tenant_id', true)::uuid)`) apply -- the
    enforcement that covers raw/non-ORM SQL too, unlike TenantOwned's own app-layer read
    filter, which only ever sees ORM queries.
    """
    from app.platform.tenancy.context import get_current_tenant

    ctx = get_current_tenant()
    if ctx is not None:
        connection.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(ctx.tenant_id)})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
