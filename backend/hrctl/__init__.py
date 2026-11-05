"""hrctl CLI scripts (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 3, Part 13 section B).

Every hrctl script is a standalone entry point, not run through app.main -- which is
where TenantOwned's insert-auto-populate hook and the ORM read filter normally get wired
up (see app/main.py's own register_tenant_owned_events/install_tenant_read_filter calls).
Doing it here too, once, at package import time, means any code a script calls that
relies on the current TenantContext to auto-populate a TenantOwned row's tenant_id (e.g.
platform.secrets.store.DbEncryptedSecretStore creating its own SecretScope row) works the
same way it does inside the real app -- found the hard way: hrctl.migrate_connections's
first real run hit a bare RLS violation because this wasn't done, from a SecretScope
insert with tenant_id left NULL.
"""

import app.models  # noqa: F401  -- registers every model on Base.metadata
from app.core.database import Base
from app.platform.tenancy.mixins import install_tenant_read_filter, register_tenant_owned_events

register_tenant_owned_events(Base)
install_tenant_read_filter()
