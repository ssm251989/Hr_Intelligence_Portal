"""File-upload antivirus hook (docs/HRMS_COMPLETE_SPEC.txt Part 13 section D: "file upload
AV scan hook (ClamAV)"). Speaks clamd's INSTREAM protocol over TCP directly -- no extra
dependency. With no `CLAMAV_HOST` configured the scan is skipped (dev); with
`AV_SCAN_REQUIRED=true` an unreachable scanner rejects the upload (fail closed, prod)."""

import socket
import struct
from dataclasses import dataclass

from app.core.config import settings

_CHUNK = 64 * 1024


@dataclass
class ScanResult:
    status: str  # clean | infected | skipped | error
    detail: str = ""


class UploadRejectedError(Exception):
    pass


def scan_bytes(content: bytes) -> ScanResult:
    if not settings.CLAMAV_HOST:
        return ScanResult("skipped", "no scanner configured")
    try:
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=10) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(content), _CHUNK):
                chunk = content[i:i + _CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = sock.recv(4096).decode("utf-8", "replace").strip("\0").strip()
    except OSError as exc:
        return ScanResult("error", type(exc).__name__)
    if reply.endswith("OK"):
        return ScanResult("clean")
    if "FOUND" in reply:
        return ScanResult("infected", reply.split(":", 1)[-1].replace("FOUND", "").strip())
    return ScanResult("error", reply[:200])


def ensure_clean(content: bytes) -> ScanResult:
    """Call before persisting any uploaded file."""
    result = scan_bytes(content)
    if result.status == "infected":
        raise UploadRejectedError(f"The file was rejected by the virus scanner ({result.detail}).")
    if result.status == "error" and settings.AV_SCAN_REQUIRED:
        raise UploadRejectedError("The file couldn't be virus-scanned right now. Please try again shortly.")
    return result
