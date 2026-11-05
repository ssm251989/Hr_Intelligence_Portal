"""Part 19.2c: the PLATFORM system mailbox and CTD Techs-only platform settings.

Owner decision 2026-10-03 ("for sending use HR admin mail only"): activation emails go out through
CTD Techs' OWN HR admin mailbox -- the company mailbox of the installation owner (CTD Techs,
tenant #1), route email.outbound.default -- never through the requesting company's mailbox.
That is mode "hr_admin" (the default). Mode "smtp" (a separate SMTP server set with
`hrctl platform mailbox set`, password in the control-plane SecretStore, or PLATFORM_SMTP_* env)
is kept only for development (e.g. mailpit) and is switched with `hrctl platform settings set
mailbox.mode smtp`.

A failed send raises MailError with a plain reason (not set up / sign-in failed / can't reach
the server / secure connection failed / timed out / address refused) -- recorded in the request
history and the backend log, never shown to a company.

Platform settings (defaults below) live in the same `platform_config` table: escalation time,
send to all priorities, resend cooldown / daily limit, support phone / email / hours.
"""

import logging
import smtplib
import socket
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

log = logging.getLogger(__name__)

MAILBOX_KEY = "platform.mailbox"
PASSWORD_REF = "platform-mailbox-password"
OWNER_DOMAIN = "ctdtechs.com"

DEFAULTS: dict = {
    "mailbox.mode": "hr_admin",  # hr_admin (CTD Techs' HR admin mailbox) | smtp (development only)
    "activation.escalation_minutes": 24 * 60,
    "activation.send_all": False,
    "activation.resend_cooldown_minutes": 15,
    "activation.resend_max_per_day": 5,
    "support.phone": "",
    "support.email": "",
    "support.hours": "",
}


class MailError(Exception):
    """`reason` is plain words; `recipient_refused` = the server took the mail but refused this address."""

    def __init__(self, reason: str, *, recipient_refused: bool = False):
        super().__init__(reason)
        self.reason, self.recipient_refused = reason, recipient_refused


def _cp():
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal

    return ControlPlaneSessionLocal()


# ---------------------------------------------------------------- platform settings

def get_setting(key: str):
    from app.platform.tenancy.models_cp import PlatformConfig

    cp_db = _cp()
    try:
        row = cp_db.get(PlatformConfig, key)
        return row.value_json if row is not None else DEFAULTS.get(key)
    finally:
        cp_db.close()


def all_settings() -> dict:
    return {k: get_setting(k) for k in DEFAULTS}


def set_setting(key: str, value, actor: str) -> None:
    from app.platform.tenancy.models_cp import PlatformConfig, SuperAdminAudit

    if key not in DEFAULTS:
        raise ValueError(f"Unknown platform setting {key!r}")
    cp_db = _cp()
    try:
        row = cp_db.get(PlatformConfig, key)
        old = row.value_json if row is not None else DEFAULTS[key]
        if row is None:
            row = PlatformConfig(key=key, value_json=value)
            cp_db.add(row)
        row.value_json, row.updated_by, row.updated_at = value, actor, datetime.now(timezone.utc)
        cp_db.add(SuperAdminAudit(admin_email=actor[:255], action="platform_setting_changed", details_json={"key": key, "old": old, "new": value}))
        cp_db.commit()
    finally:
        cp_db.close()


# ---------------------------------------------------------------- mailbox config

def _stored() -> Optional[dict]:
    from app.platform.tenancy.models_cp import PlatformConfig

    cp_db = _cp()
    try:
        row = cp_db.get(PlatformConfig, MAILBOX_KEY)
        return dict(row.value_json) if row is not None and isinstance(row.value_json, dict) else None
    finally:
        cp_db.close()


def _password() -> str:
    from app.platform.secrets.store import SecretNotFoundError
    from app.platform.tenancy.provisioning import _store

    cp_db = _cp()
    try:
        try:
            return _store(cp_db).get(PASSWORD_REF)
        except SecretNotFoundError:
            return ""
    finally:
        cp_db.close()


def _owner_tenant():
    """CTD Techs' own company (installation owner = tenant #1)."""
    from app.platform.tenancy.context import TENANT_1_ID
    from app.platform.tenancy.models_cp import Tenant

    cp_db = _cp()
    try:
        return cp_db.get(Tenant, TENANT_1_ID)
    finally:
        cp_db.close()


def _hr_admin_connection(fn):
    """Runs fn(db, ctx, connection) with CTD Techs' HR admin mailbox (outbound) connection."""
    from app.platform.connectors.router import ConnectorRouter, NoConnectionForPurposeError
    from app.platform.tenancy.context import get_current_tenant, tenant_context
    from app.platform.tenancy.provisioning import tenant_session

    owner = _owner_tenant()
    if owner is None:
        raise MailError("CTD Techs' own company isn't set up on this installation.")
    with tenant_context(owner.id, owner.slug, owner.isolation):
        db = tenant_session(owner)
        try:
            try:
                resolved = ConnectorRouter(db).resolve("email.outbound.default")
            except NoConnectionForPurposeError as exc:
                raise MailError("CTD Techs' HR admin mailbox isn't connected (Settings > Communication > Mailboxes).") from exc
            return fn(db, get_current_tenant(), resolved.connection)
        finally:
            db.close()


def mailbox() -> dict:
    """The effective sending mailbox. `password_set`, never the password."""
    if (get_setting("mailbox.mode") or "hr_admin") == "hr_admin":
        try:
            def describe(db, ctx, conn):
                cfg = conn.config_json or {}
                return {"host": cfg.get("host", ""), "port": cfg.get("port"), "user": cfg.get("username"),
                        "from_address": cfg.get("from_address") or cfg.get("username"), "from_name": "CTD Techs HR",
                        "connection": conn.name, "source": "hr_admin", "password_set": bool(conn.secret_ref)}
            return _hr_admin_connection(describe)
        except MailError as exc:
            return {"host": "", "source": "none", "password_set": False, "problem": exc.reason}
    stored = _stored()
    if stored and stored.get("host"):
        return {**stored, "source": "console", "password_set": bool(_password())}
    if settings.PLATFORM_SMTP_HOST:
        return {"host": settings.PLATFORM_SMTP_HOST, "port": settings.PLATFORM_SMTP_PORT, "user": settings.PLATFORM_SMTP_USER,
                "starttls": settings.PLATFORM_SMTP_STARTTLS, "from_name": "CTD Techs HRMS", "from_address": _from_address_env(),
                "source": "env", "password_set": bool(settings.PLATFORM_SMTP_PASSWORD)}
    return {"host": "", "source": "none", "password_set": False}


def _from_address_env() -> str:
    raw = settings.PLATFORM_MAIL_FROM
    return raw.split("<", 1)[1].rstrip(">").strip() if "<" in raw else raw.strip()


def set_mailbox(*, host: str, port: int, user: str, starttls: bool, from_name: str, from_address: str,
                password: Optional[str], actor: str) -> dict:
    from app.platform.tenancy.models_cp import PlatformConfig, SuperAdminAudit
    from app.platform.tenancy.provisioning import _store, put_or_rotate

    from_address = (from_address or "").strip().lower()
    domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else ""
    if domain != OWNER_DOMAIN and not domain.endswith("." + OWNER_DOMAIN):
        raise MailError(f"The from address must be an @{OWNER_DOMAIN} address.")
    if not host.strip() or not (0 < int(port) < 65536):
        raise MailError("Enter the mail server name and port.")
    value = {"host": host.strip(), "port": int(port), "user": user.strip(), "starttls": bool(starttls),
             "from_name": (from_name or "CTD Techs HRMS").strip(), "from_address": from_address}
    cp_db = _cp()
    try:
        old = cp_db.get(PlatformConfig, MAILBOX_KEY)
        old_value = dict(old.value_json) if old is not None else None
        if old is None:
            cp_db.add(PlatformConfig(key=MAILBOX_KEY, value_json=value, updated_by=actor))
        else:
            old.value_json, old.updated_by, old.updated_at = value, actor, datetime.now(timezone.utc)
        cp_db.add(SuperAdminAudit(admin_email=actor[:255], action="platform_mailbox_set",
                                  details_json={"old": old_value, "new": value, "password_changed": password is not None}))
        cp_db.commit()
        if password is not None:
            put_or_rotate(_store(cp_db), PASSWORD_REF, password, created_by=actor)
    finally:
        cp_db.close()
    return mailbox()


# ---------------------------------------------------------------- sending

def _creds() -> tuple[dict, str]:
    m = mailbox()
    if m["source"] == "console":
        return m, _password()
    if m["source"] == "env":
        return m, settings.PLATFORM_SMTP_PASSWORD
    raise MailError("The platform mailbox isn't set up yet (no mail server).")


def _classify(error: str) -> MailError:
    low = error.lower()
    if "535" in low or "534" in low or "authentication" in low or "username and password" in low:
        return MailError(f"Signing in to the HR admin mailbox failed ({error[:160]}).")
    if "recipient" in low or "550" in low or "553" in low:
        return MailError(f"The mail server refused the address ({error[:160]}).", recipient_refused=True)
    if "timed out" in low or "timeout" in low:
        return MailError("The mail server didn't answer in time (timeout).")
    if "ssl" in low or "tls" in low:
        return MailError(f"The secure (TLS) connection to the mail server failed ({error[:160]}).")
    if "getaddrinfo" in low or "refused" in low or "unreachable" in low or "10061" in low:
        return MailError(f"Can't reach the mail server ({error[:160]}).")
    return MailError(f"The HR admin mailbox couldn't send ({error[:160]}).")


def send(to: list[str], subject: str, body: str) -> None:
    if (get_setting("mailbox.mode") or "hr_admin") == "hr_admin":
        from app.platform.comms.service import _get_adapter_and_secrets
        from app.platform.connectors.capabilities import OutboundEmail
        from app.platform.connectors.providers import register_all

        register_all()  # idempotent; hrctl / the scheduler don't import the connectors API

        def go(db, ctx, conn):
            adapter = _get_adapter_and_secrets(db, ctx, conn)
            return adapter.send(OutboundEmail(to=list(to), subject=subject, body_text=body))

        result = _hr_admin_connection(go)
        if not result.success:
            raise _classify(result.error or "send failed")
        return
    m, password = _creds()
    msg = EmailMessage()
    msg["From"] = f"{m.get('from_name') or 'CTD Techs HRMS'} <{m.get('from_address')}>"
    msg["To"], msg["Subject"] = ", ".join(to), subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(m["host"], int(m.get("port") or 587), timeout=20) as smtp:
            if m.get("starttls"):
                smtp.starttls(context=ssl.create_default_context())
            if m.get("user"):
                smtp.login(m["user"], password)
            refused = smtp.send_message(msg)
        if refused:
            raise MailError(f"The mail server refused: {', '.join(refused)}", recipient_refused=True)
    except MailError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"Signing in to the mail server failed ({exc.smtp_code} {_text(exc.smtp_error)}).") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"The mail server refused the address: {', '.join(exc.recipients)}", recipient_refused=True) from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise MailError(f"The mail server doesn't support this sign-in or secure connection ({exc}).") from exc
    except ssl.SSLError as exc:
        raise MailError(f"The secure (TLS) connection to the mail server failed ({exc.reason or exc}).") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise MailError("The mail server didn't answer in time (timeout).") from exc
    except (ConnectionRefusedError, socket.gaierror, OSError) as exc:
        raise MailError(f"Can't reach the mail server {m['host']}:{m.get('port')} ({exc}).") from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"The mail server rejected the message ({exc}).") from exc


def _text(raw) -> str:
    return raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)


def test(to: str, actor: str) -> dict:
    from app.platform.tenancy.models_cp import SuperAdminAudit

    ok, reason = True, None
    try:
        send([to], "Test email from the CTD Techs HRMS platform mailbox",
             f"This is a test of the platform mailbox, sent by {actor} on {datetime.now(timezone.utc).isoformat(timespec='seconds')}.\n"
             "Activation requests from companies are sent through this mailbox.\n")
    except MailError as exc:
        ok, reason = False, exc.reason
        log.warning("platform mailbox test to %s failed: %s", to, exc.reason)
    cp_db = _cp()
    try:
        cp_db.add(SuperAdminAudit(admin_email=actor[:255], action="platform_mailbox_test", details_json={"to": to, "ok": ok, "reason": reason}))
        cp_db.commit()
    finally:
        cp_db.close()
    set_last_test(ok, reason)
    return {"ok": ok, "reason": reason}


def set_last_test(ok: bool, reason: Optional[str]) -> None:
    from app.platform.tenancy.models_cp import PlatformConfig

    cp_db = _cp()
    try:
        row = cp_db.get(PlatformConfig, "platform.mailbox_status")
        value = {"ok": ok, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
        if row is None:
            cp_db.add(PlatformConfig(key="platform.mailbox_status", value_json=value))
        else:
            row.value_json = value
        cp_db.commit()
    finally:
        cp_db.close()


def health() -> dict:
    """For the console: red until activation emails can really be sent."""
    from app.platform.tenancy.models_cp import PlatformConfig

    m = mailbox()
    if m["source"] == "none":
        return {"ok": False, "reason": m.get("problem") or "the HR admin mailbox isn't connected", "mailbox": m, "last": None}
    cp_db = _cp()
    try:
        row = cp_db.get(PlatformConfig, "platform.mailbox_status")
        last = dict(row.value_json) if row is not None else None
    finally:
        cp_db.close()
    if m["source"] == "none":
        return {"ok": False, "reason": "the platform mailbox isn't set up", "mailbox": m, "last": last}
    if last is not None and not last.get("ok"):
        return {"ok": False, "reason": last.get("reason") or "the last send failed", "mailbox": m, "last": last}
    return {"ok": True, "reason": None, "mailbox": m, "last": last}
