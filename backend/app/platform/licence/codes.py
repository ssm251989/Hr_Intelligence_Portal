"""Part 32: the text codes that travel between a company and CTD Techs.

- A REQUEST is not signed (anyone may ask): "CTDREQ1.<base64url JSON>.<checksum>" - the checksum only catches a
  bad copy-paste. It carries the install id, company, admin, modules, app version, date and a random nonce.
- An APPROVAL is signed by CTD Techs' Ed25519 private key: "CTD1.<base64url JSON>.<base64url signature>". The
  signature covers the exact JSON bytes. Only the matching public key, shipped with the app
  (ctd_public_key.pem), can check it - so editing the database or the code text never switches anything on.

The CTD signing tool (tools/ctd_licence) writes the same format; tests/test_licence.py checks they agree.
"""

import base64
import hashlib
import json
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REQUEST_PREFIX = "CTDREQ1"
APPROVAL_PREFIX = "CTD1"
PUBLIC_KEY_PATH = Path(__file__).with_name("ctd_public_key.pem")
_test_key: Optional[Ed25519PublicKey] = None  # tests only (set_public_key_for_tests); never from .env


class CodeError(ValueError):
    """A code / file that cannot be used; `code` is a short reason for logs and tests."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def set_public_key_for_tests(key: Optional[Ed25519PublicKey]) -> None:
    global _test_key
    _test_key = key


def public_key() -> Optional[Ed25519PublicKey]:
    """CTD's public key built into this copy, or None when this copy has none (not set up by CTD Techs)."""
    if _test_key is not None:
        return _test_key
    if not PUBLIC_KEY_PATH.exists():
        return None
    key = serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())
    return key if isinstance(key, Ed25519PublicKey) else None


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _clean(text: str) -> str:
    return "".join((text or "").split())  # an email may wrap or indent a long code


def checksum(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()[:8]


def encode_request(payload: dict) -> str:
    body = b64e(canonical(payload))
    return f"{REQUEST_PREFIX}.{body}.{checksum(body)}"


def decode_request(text: str) -> dict:
    parts = _clean(text).split(".")
    if len(parts) != 3 or parts[0] != REQUEST_PREFIX:
        raise CodeError("This is not an HR Automation request.", "not_a_request")
    if checksum(parts[1]) != parts[2]:
        raise CodeError("The request was not copied completely - copy it again.", "bad_checksum")
    try:
        return json.loads(b64d(parts[1]))
    except ValueError as exc:
        raise CodeError("The request was not copied completely - copy it again.", "bad_body") from exc


def verify_signed(body: bytes, signature: bytes) -> None:
    key = public_key()
    if key is None:
        raise CodeError("This copy isn't set up by CTD Techs.", "no_public_key")
    try:
        key.verify(signature, body)
    except InvalidSignature as exc:
        raise CodeError("This code is not from CTD Techs or was changed.", "bad_signature") from exc


def decode_approval(text: str) -> dict:
    """The approval's payload once CTD Techs' signature checks out (raises CodeError otherwise)."""
    parts = _clean(text).split(".")
    if len(parts) != 3 or parts[0] != APPROVAL_PREFIX:
        raise CodeError("This is not an approval code from CTD Techs.", "not_an_approval")
    try:
        body, signature = b64d(parts[1]), b64d(parts[2])
    except ValueError as exc:
        raise CodeError("The code was not copied completely - copy it again.", "bad_body") from exc
    verify_signed(body, signature)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise CodeError("The code was not copied completely - copy it again.", "bad_body") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise CodeError("This code is for another version of the app.", "bad_version")
    return payload


def clean_code(text: str) -> str:
    return _clean(text)
