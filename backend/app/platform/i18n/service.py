"""i18n (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 6): `locales/*.json` bundles (English,
Hindi, Tamil -- the 3 launch languages) + a tenant's own `i18n_overrides` table so a client
can rename "Employee" to "Associate", "Requisition" to "MRF", etc. WITHOUT touching the
base bundle.

**Scoped down** (see docs/build_log.md's own Part 6 note): the base bundles seed a
REPRESENTATIVE key set (nav labels, common actions, a few renameable entity names) proving
the override mechanism end-to-end, not an exhaustive translation of every string in this
app's existing frontend -- that's its own large, separate mechanical sweep (every page's
every hardcoded English string would need a key), same class of decision as Part 5's
"don't retrofit authz onto every router."
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.metadata import I18nOverride
from app.platform.tenancy.context import TenantContext

_LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "hi", "ta")


@lru_cache(maxsize=8)
def _bundle(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def base_bundle(locale: str) -> dict[str, str]:
    return dict(_bundle(locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE))


def overrides_for(db: Session, tenant: TenantContext, locale: str) -> dict[str, str]:
    rows = db.query(I18nOverride).filter(I18nOverride.tenant_id == tenant.tenant_id, I18nOverride.locale == locale).all()
    return {row.key: row.value for row in rows}


def merged_bundle(db: Session, tenant: TenantContext, locale: str) -> dict[str, str]:
    """Base bundle for `locale`, filled in with `en` for any key the requested locale's
    own bundle is missing (partial translations still render SOMETHING, never a raw
    key), then the tenant's own overrides layered on top -- overrides win regardless of
    which bundle a key came from."""
    merged = base_bundle(DEFAULT_LOCALE)
    merged.update(base_bundle(locale))
    merged.update(overrides_for(db, tenant, locale))
    return merged


def translate(db: Session, tenant: TenantContext, locale: str, key: str, default: Optional[str] = None) -> str:
    override = db.query(I18nOverride).filter(I18nOverride.tenant_id == tenant.tenant_id, I18nOverride.locale == locale, I18nOverride.key == key).first()
    if override is not None:
        return override.value
    value = base_bundle(locale).get(key) or base_bundle(DEFAULT_LOCALE).get(key)
    if value is not None:
        return value
    return default if default is not None else key


def set_override(db: Session, tenant: TenantContext, locale: str, key: str, value: str) -> I18nOverride:
    row = db.query(I18nOverride).filter(I18nOverride.tenant_id == tenant.tenant_id, I18nOverride.locale == locale, I18nOverride.key == key).first()
    if row is None:
        row = I18nOverride(tenant_id=tenant.tenant_id, locale=locale, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    return row


def delete_override(db: Session, tenant: TenantContext, override_id) -> None:
    row = db.get(I18nOverride, override_id)
    if row is not None and row.tenant_id == tenant.tenant_id:
        db.delete(row)
        db.commit()
