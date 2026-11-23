"""CTD Techs' signing tool - the only place approvals are made. Runs on a CTD PC; never shipped to clients.

Keys live in CTD_LICENCE_HOME (default ~/.ctd_licence): ctd_private_key.pem (encrypted with a passphrase) and
ctd_public_key.pem (copied into the app at backend/app/platform/licence/ctd_public_key.pem before a zip is built).
The text formats match backend/app/platform/licence/codes.py (tests/test_licence.py checks they agree).
"""

import base64
import csv
import getpass
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

OWNER_DOMAIN = "ctdtechs.com"
REQUEST_PREFIX = "CTDREQ1"
APPROVAL_PREFIX = "CTD1"
PRIVATE = "ctd_private_key.pem"
PUBLIC = "ctd_public_key.pem"
LOG = "approvals_log.csv"


class ToolError(Exception):
    pass


def home() -> Path:
    return Path(os.getenv("CTD_LICENCE_HOME") or Path.home() / ".ctd_licence")


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _clean(text: str) -> str:
    return "".join((text or "").split())


def passphrase(confirm: bool = False) -> bytes:
    value = os.getenv("CTD_LICENCE_PASSPHRASE")  # for scripted use only; normally typed
    if value is None:
        value = getpass.getpass("Passphrase for the CTD private key: ")
        if confirm and getpass.getpass("Type it again: ") != value:
            raise ToolError("The passphrases do not match.")
    if len(value) < 12:
        raise ToolError("Use a passphrase of at least 12 characters.")
    return value.encode()


# ---------------------------------------------------------------- keys


def keygen(folder: Optional[Path] = None, *, force: bool = False) -> tuple[Path, Path]:
    folder = folder or home()
    folder.mkdir(parents=True, exist_ok=True)
    priv_path, pub_path = folder / PRIVATE, folder / PUBLIC
    if priv_path.exists() and not force:
        raise ToolError(f"A private key already exists in {folder}. A new key pair means a new zip build for every client - "
                        "use --force only if that is what you want (see docs/CTD_LICENCE_RUNBOOK.md).")
    key = Ed25519PrivateKey.generate()
    priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.BestAvailableEncryption(passphrase(confirm=True))))
    pub_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    try:
        os.chmod(priv_path, 0o600)
    except OSError:
        pass
    return priv_path, pub_path


def private_key(folder: Optional[Path] = None) -> Ed25519PrivateKey:
    path = (folder or home()) / PRIVATE
    if not path.exists():
        raise ToolError(f"No private key in {path.parent}. Run: python -m ctd_licence keygen")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=passphrase())
    except ValueError as exc:
        raise ToolError("Wrong passphrase.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ToolError("That key is not an Ed25519 key.")
    return key


def public_key(folder: Optional[Path] = None, path: Optional[Path] = None) -> Ed25519PublicKey:
    path = path or (folder or home()) / PUBLIC
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ToolError("That key is not an Ed25519 key.")
    return key


# ---------------------------------------------------------------- CTD config


def make_config(approver: str, *, support: Optional[dict] = None, out: Optional[Path] = None, folder: Optional[Path] = None) -> tuple[Path, Path]:
    email = (approver or "").strip().lower()
    if "@" not in email or email.rsplit("@", 1)[1] != OWNER_DOMAIN:
        raise ToolError(f"The approver must be a @{OWNER_DOMAIN} address.")
    data = json.dumps({"approver_email": email, "support": {k: v for k, v in (support or {}).items() if v},
                       "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2).encode()
    signature = private_key(folder).sign(data)
    out = out or Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    cfg, sig = out / "ctd_config.json", out / "ctd_config.json.sig"
    cfg.write_bytes(data)
    sig.write_text(base64.b64encode(signature).decode() + "\n")
    return cfg, sig


# ---------------------------------------------------------------- requests and approvals


def decode_request(text: str) -> dict:
    parts = _clean(text).split(".")
    if len(parts) != 3 or parts[0] != REQUEST_PREFIX:
        raise ToolError("That is not an HR Automation request (it starts with CTDREQ1.).")
    if hashlib.sha256(parts[1].encode()).hexdigest()[:8] != parts[2]:
        raise ToolError("The request was not copied completely (checksum) - ask the company to send it again.")
    return json.loads(b64d(parts[1]))


def approval_payload(request: dict, *, modules: Optional[list[str]] = None, valid_until: Optional[str] = None) -> dict:
    if valid_until:
        try:
            date.fromisoformat(valid_until)
        except ValueError as exc:
            raise ToolError("--valid-until must be a date like 2027-12-31.") from exc
    for field in ("install_id", "slug", "nonce", "kind"):
        if not request.get(field):
            raise ToolError(f"The request has no {field}.")
    payload = {"v": 1, "kind": request["kind"], "install_id": request["install_id"], "slug": request["slug"],
               "modules": sorted(set(modules if modules is not None else request.get("modules") or [])),
               "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "nonce": request["nonce"]}
    if valid_until:
        payload["valid_until"] = valid_until
    return payload


def sign_approval(payload: dict, key: Ed25519PrivateKey) -> str:
    body = canonical(payload)
    return f"{APPROVAL_PREFIX}.{b64e(body)}.{b64e(key.sign(body))}"


def read_approval(text: str, key: Optional[Ed25519PublicKey]) -> tuple[dict, Optional[bool]]:
    """(payload, signature valid?) - valid is None when no public key is given."""
    parts = _clean(text).split(".")
    if len(parts) != 3 or parts[0] != APPROVAL_PREFIX:
        raise ToolError("That is not an approval code (it starts with CTD1.).")
    body, signature = b64d(parts[1]), b64d(parts[2])
    valid = None
    if key is not None:
        try:
            key.verify(signature, body)
            valid = True
        except InvalidSignature:
            valid = False
    return json.loads(body), valid


def log_approval(request: dict, payload: dict, folder: Optional[Path] = None) -> Path:
    path = (folder or home()) / LOG
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["approved_at", "approved_by", "kind", "request_number", "company", "slug", "admin_email", "modules", "valid_until",
                        "install_id", "nonce"])
        w.writerow([payload["issued_at"], getpass.getuser(), payload["kind"], request.get("number"), request.get("company"), payload["slug"],
                    request.get("admin_email"), " ".join(payload["modules"]), payload.get("valid_until") or "", payload["install_id"],
                    payload["nonce"]])
    return path
