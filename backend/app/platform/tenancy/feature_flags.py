"""Feature flag checks (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 1's own
`feature_flags`/`tenant_feature_flags` control-plane tables) -- built by Part 2 but never
actually read by any caller until Part 6's `branding.custom_css` gate needed a real one.
`is_enabled()` resolution order: a tenant's own explicit `tenant_feature_flags` override,
else the flag's own registered `default_bool`, else `False` for a flag nobody's
registered at all (never treated as "on" by omission).
"""

from sqlalchemy.orm import Session

from app.platform.tenancy.models_cp import FeatureFlag, TenantFeatureFlag

_registered = False


def register_flag(db: Session, key: str, *, description: str = "", default_bool: bool = False) -> None:
    existing = db.get(FeatureFlag, key)
    if existing is None:
        db.add(FeatureFlag(key=key, description=description, default_bool=default_bool))
        db.commit()


def register_all(db: Session) -> None:
    """Idempotent, same pattern as every other module's own register_all()."""
    global _registered
    if _registered:
        return
    register_flag(db, "branding.custom_css", description="Custom CSS slot on the tenant's brand theme (Part 6 section 5)", default_bool=False)
    _registered = True


def is_enabled(db: Session, tenant_id, key: str) -> bool:
    override = db.query(TenantFeatureFlag).filter(TenantFeatureFlag.tenant_id == tenant_id, TenantFeatureFlag.key == key).first()
    if override is not None:
        return override.value_bool
    flag = db.get(FeatureFlag, key)
    return bool(flag.default_bool) if flag is not None else False


def set_for_tenant(db: Session, tenant_id, key: str, value: bool) -> None:
    override = db.query(TenantFeatureFlag).filter(TenantFeatureFlag.tenant_id == tenant_id, TenantFeatureFlag.key == key).first()
    if override is None:
        db.add(TenantFeatureFlag(tenant_id=tenant_id, key=key, value_bool=value))
    else:
        override.value_bool = value
    db.commit()
