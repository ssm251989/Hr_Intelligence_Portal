"""Fix 2026-10-04: every link in an email (interview pickers, confirmations, logo, careers) is built
from ONE address -- the company setting `org.public_base_url` ("Public address for links in
emails", e.g. https://hr.ctdtechs.com), falling back to the server's APP_BASE_URL. Never hardcoded.
A localhost address only opens on this computer, so Health warns about it."""

from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def public_base_url(db=None) -> str:
    from app.core.config import settings
    from app.platform.tenancy.context import get_current_tenant

    value = ""
    tenant = get_current_tenant()
    if tenant is not None:
        own = db is None
        if own:
            from app.core.database import SessionLocal

            db = SessionLocal()
        try:
            from app.platform.settings.resolver import SettingContext, SettingsService

            value = (SettingsService(db).get("org.public_base_url", SettingContext(tenant=tenant)) or "").strip()
        except Exception:  # noqa: BLE001 -- a link must always be built
            value = ""
        finally:
            if own:
                db.close()
    return (value or settings.APP_BASE_URL).rstrip("/")


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in LOCAL_HOSTS
