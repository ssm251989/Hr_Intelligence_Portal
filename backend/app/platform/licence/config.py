"""Part 32.1: the signed "CTD config" - the ONE approver address (only CTD Techs can set it) and CTD's contacts.

Files next to this module: ctd_config.json + ctd_config.json.sig (base64 Ed25519 signature of the exact JSON bytes),
shipped in the zip. On-prem the client can only put a NEW file from CTD in place (Settings > Licence > "Load CTD
file", which checks the signature first); cloud: CTD deploys it. A missing, edited or unsigned file -> no approver:
the app says "This copy isn't set up by CTD Techs" and refuses access and module requests; what is already active
keeps working.
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

from app.platform.licence.codes import CodeError, verify_signed

OWNER_DOMAIN = "ctdtechs.com"
DIR = Path(__file__).parent
CONFIG_PATH = DIR / "ctd_config.json"
SIG_PATH = DIR / "ctd_config.json.sig"
NOT_SET_UP = "This copy isn't set up by CTD Techs. Ask CTD Techs for the CTD file and load it in Settings > Licence."
_cache: dict = {}


def check(config_bytes: bytes, sig_text: str) -> dict:
    """The config's content when CTD's signature checks out and the approver is a CTD address; CodeError otherwise."""
    try:
        signature = base64.b64decode("".join(sig_text.split()))
    except ValueError as exc:
        raise CodeError("The signature file is damaged.", "bad_signature_file") from exc
    verify_signed(config_bytes, signature)
    try:
        data = json.loads(config_bytes)
    except ValueError as exc:
        raise CodeError("The CTD file is damaged.", "bad_config") from exc
    email = str(data.get("approver_email") or "").strip().lower()
    if "@" not in email or email.rsplit("@", 1)[1] != OWNER_DOMAIN:
        raise CodeError(f"The approver must be a @{OWNER_DOMAIN} address.", "bad_approver")
    return {**data, "approver_email": email}


def load() -> Optional[dict]:
    """The verified config, or None (missing / edited / unsigned). Re-read at most every 60 s."""
    hit = _cache.get("config")
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = None
    if CONFIG_PATH.exists() and SIG_PATH.exists():
        try:
            value = check(CONFIG_PATH.read_bytes(), SIG_PATH.read_text())
        except CodeError:
            value = None
    _cache["config"] = (time.monotonic() + 60, value)
    return value


def clear_cache() -> None:
    _cache.clear()


def approver_email() -> Optional[str]:
    cfg = load()
    return cfg["approver_email"] if cfg else None


def support() -> dict:
    cfg = load() or {}
    return dict(cfg.get("support") or {})


def install(config_bytes: bytes, sig_text: str) -> dict:
    """Settings > Licence > "Load CTD file": checks the signature, then puts the files in place."""
    data = check(config_bytes, sig_text)
    CONFIG_PATH.write_bytes(config_bytes)
    SIG_PATH.write_text("".join(sig_text.split()) + "\n")
    clear_cache()
    return data
