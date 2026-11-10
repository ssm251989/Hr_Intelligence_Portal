"""backend/.env: built and written so that it can't break.

- Database URLs are built here, with the user name and password URL-encoded
  (`Admin@123` -> `Admin%40123`), and the psycopg2 driver named explicitly.
- Each value is checked for line breaks before writing (a missing line break once glued
  SECRET_BACKEND onto a database URL).
- The file is written to a temporary file and then swapped in (never half-written), keeps every
  other line the person had, and is read back to prove each value comes out exactly as intended.
"""

import os
import re
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def dsn(user: str, password: str, host: str, port: int, database: str) -> str:
    return f"postgresql+psycopg2://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{int(port)}/{database}"


def new_secret_key() -> str:
    return secrets.token_urlsafe(48)


def new_master_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _check(key: str, value: str) -> None:
    if not _KEY.match(key):
        raise ValueError(f"bad .env key {key!r}")
    if any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{key} must be on one line")


def _render(value: str) -> str:
    """Quote values with spaces or # so dotenv reads them back unchanged."""
    if value == "" or re.match(r"^[A-Za-z0-9_@%+=:/.,~!?*()\[\]{}<>|^&$-]+$", value) and "#" not in value and '"' not in value and "'" not in value:
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write(path: Path, values: dict[str, str], *, keep_existing: bool = True) -> Path:
    """Set `values` in the .env at `path` (other lines kept), atomically, then verify."""
    for k, v in values.items():
        _check(k, str(v))
    path = Path(path)
    lines: list[str] = []
    if keep_existing and path.exists():
        raw = path.read_text(encoding="utf-8-sig")
        lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(1) in values:
            if m.group(1) in done:
                continue  # a duplicate key further down would silently win -- drop it
            out.append(f"{m.group(1)}={_render(str(values[m.group(1)]))}")
            done.add(m.group(1))
        else:
            out.append(line)
    while out and out[-1] == "":
        out.pop()
    for k, v in values.items():
        if k not in done:
            out.append(f"{k}={_render(str(v))}")
    text = "\n".join(out) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    _restrict(path)
    verify(path, values)
    return path


def verify(path: Path, expected: dict[str, str]) -> None:
    from dotenv import dotenv_values

    got = dotenv_values(path)
    wrong = [k for k, v in expected.items() if got.get(k) != str(v)]
    if wrong:
        raise RuntimeError(f".env check failed for: {', '.join(wrong)}")


def _restrict(path: Path) -> None:
    """Only the account that runs the app may read .env (it holds passwords)."""
    try:
        if os.name == "nt":
            import getpass
            import subprocess

            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:(R,W)", "/grant:r", "SYSTEM:(F)",
                            "/grant:r", "Administrators:(F)"], check=False, capture_output=True)
        else:
            os.chmod(path, 0o600)
    except Exception:  # noqa: BLE001 -- best effort; the installer also sets folder permissions
        pass


def read(path: Path) -> dict[str, Optional[str]]:
    from dotenv import dotenv_values

    return dict(dotenv_values(path))
