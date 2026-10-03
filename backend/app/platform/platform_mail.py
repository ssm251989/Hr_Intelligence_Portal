"""Part 19.2c: the PLATFORM system mailbox and CTD Techs-only platform settings.

The mailbox CTD Techs sends activation emails through -- never a company's own mail connection.
Set in Super-admin console > Platform mailbox or `hrctl platform mailbox set` (control plane
`platform_config["platform.mailbox"]`; the password only in the control-plane SecretStore).
PLATFORM_SMTP_* env values are the fallback (e.g. a dev mailpit).

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


def mailbox() -> dict:
    """The effective mailbox (console/hrctl first, env fallback). `password_set`, never the password."""
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


def send(to: list[str], subject: str, body: str) -> None:
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
