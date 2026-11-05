"""The control plane's own database (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 1) --
tenants, plans, module enablement -- deliberately a SEPARATE engine/Base/session from
app.core.database's tenant-data one, even under TENANCY_MODE=single where there is exactly
one tenant row. Keeping the split from day one means control-plane and tenant-data
migrations, backups, and connection pools never have to be untangled later.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

control_plane_engine = create_engine(settings.APP_CONTROL_PLANE_DATABASE_URL)
ControlPlaneSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=control_plane_engine)

ControlPlaneBase = declarative_base()


def get_control_plane_db():
    db = ControlPlaneSessionLocal()
    try:
        yield db
    finally:
        db.close()
