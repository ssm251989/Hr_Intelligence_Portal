"""hrctl backup -- nightly database backup (Part 17.13). See docs/BACKUP_RESTORE.md.

    python -m hrctl.backup run [--dir backups] [--keep 14]    dump the app + control-plane databases
    python -m hrctl.backup list [--dir backups]               what is there

Uses PostgreSQL's own pg_dump (custom format, compressed) so a restore is `pg_restore`.
Also zips the uploads/ folder (resumes, logos, media) next to the dumps. Keeps the newest
--keep sets and deletes only older files it made itself (named hrms-*). Never touches the
databases' data.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parent.parent
_CANDIDATE_BINS = [r"C:\Program Files\PostgreSQL\17\bin", r"C:\Program Files\PostgreSQL\16\bin", r"C:\Program Files\PostgreSQL\15\bin"]


def _pg_dump() -> str:
    if os.getenv("PG_DUMP"):
        return os.environ["PG_DUMP"]
    found = shutil.which("pg_dump")
    if found:
        return found
    for d in _CANDIDATE_BINS:
        exe = Path(d) / "pg_dump.exe"
        if exe.is_file():
            return str(exe)
    raise SystemExit("pg_dump not found. Install the PostgreSQL client tools or set PG_DUMP to its path.")


def _dump(dsn: str, out: Path) -> None:
    u = urlparse(dsn.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+psycopg://", "postgresql://"))
    env = {**os.environ, "PGPASSWORD": u.password or ""}
    cmd = [_pg_dump(), "-Fc", "-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", u.username or "postgres",
           "-d", (u.path or "/").lstrip("/"), "-f", str(out)]
    subprocess.run(cmd, check=True, env=env)


def run(backup_dir: Path, keep: int) -> dict:
    from app.core.config import settings

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    made = []
    for name, dsn in (("app", settings.DATABASE_URL), ("control", settings.CONTROL_PLANE_DATABASE_URL)):
        if not dsn:
            continue
        out = backup_dir / f"hrms-{name}-{stamp}.dump"
        _dump(dsn, out)
        made.append(out.name)
    uploads = BACKEND / "uploads"
    if uploads.is_dir():
        made.append(Path(shutil.make_archive(str(backup_dir / f"hrms-uploads-{stamp}"), "zip", uploads)).name)
    # keep the newest `keep` sets of each kind; only our own hrms-* files are ever removed
    removed = []
    for kind in ("app", "control", "uploads"):
        files = sorted(backup_dir.glob(f"hrms-{kind}-*"), key=lambda p: p.name, reverse=True)
        for old in files[keep:]:
            old.unlink()
            removed.append(old.name)
    return {"made": made, "removed_old": removed, "dir": str(backup_dir)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl backup")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dir", default=str(BACKEND.parent / "backups"))
    r.add_argument("--keep", type=int, default=14)
    ls = sub.add_parser("list")
    ls.add_argument("--dir", default=str(BACKEND.parent / "backups"))
    args = parser.parse_args(argv)
    if args.command == "run":
        import json

        print(json.dumps(run(Path(args.dir), args.keep), indent=2))
    else:
        for f in sorted(Path(args.dir).glob("hrms-*")):
            print(f"{f.name}  {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
