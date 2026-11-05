"""Restore drill (docs/HRMS_COMPLETE_SPEC.txt Part 13 section C): restores a backup dump into
a THROWAWAY database the drill creates itself (`hrms_restore_drill_<timestamp>`), checks it
(schema revision present, tenant row counts), prints a report, then drops ONLY that
throwaway database. It never touches a live database; run it monthly and keep the report.

    python -m scripts.restore_drill --dump /backups/<stamp>/installation.dump [--keep]
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text


def main(argv=None) -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(prog="restore_drill")
    parser.add_argument("--dump", required=True)
    parser.add_argument("--keep", action="store_true", help="leave the drill database for inspection")
    args = parser.parse_args(argv)
    if shutil.which("pg_restore") is None:
        print("error: pg_restore not on PATH", file=sys.stderr)
        return 2
    scratch = f"hrms_restore_drill_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    admin = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    scratch_dsn = urlunparse(urlparse(settings.DATABASE_URL)._replace(path=f"/{scratch}"))
    started = datetime.now(timezone.utc)
    result = subprocess.run(["pg_restore", "--no-owner", "--dbname", scratch_dsn, args.dump], capture_output=True, text=True)
    report = {"dump": args.dump, "database": scratch, "restore_exit": result.returncode, "seconds": None, "checks": {}}
    try:
        engine = create_engine(scratch_dsn)
        with engine.connect() as conn:
            report["checks"]["alembic_revision"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar() if conn.execute(
                text("SELECT to_regclass('public.alembic_version')")).scalar() else None
            for table in ("tenants", "users", "employees", "candidates", "applications", "audit_log"):
                if conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar():
                    report["checks"][f"rows.{table}"] = conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()
        engine.dispose()
    finally:
        report["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        if not args.keep:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}"'))  # the drill's own throwaway DB only
        admin.dispose()
    print(report)
    return 0 if result.returncode == 0 and report["checks"].get("alembic_revision") else 1


if __name__ == "__main__":
    sys.exit(main())
