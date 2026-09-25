"""Per-tenant backups (docs/HRMS_COMPLETE_SPEC.txt Part 13 section C): one `pg_dump -Fc`
per distinct tenant database (dedicated tenants get their own file; shared_rls tenants are
inside the installation dump) plus the control plane, into a dated directory, then prunes
dumps older than the retention window. RDS automated backups/PITR (Terraform
backup_retention_days) are the primary mechanism in AWS -- this is the portable,
provider-independent layer, and what `restore_drill.py` restores from.

    python -m scripts.backup_tenants --out /backups [--retention-days 30] [--dry-run]
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def targets() -> dict[str, list[str]]:
    from app.core.config import settings
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import admin_dsn_for

    out: dict[str, list[str]] = {settings.CONTROL_PLANE_DATABASE_URL: ["control-plane"], settings.DATABASE_URL: ["installation"]}
    cp_db = ControlPlaneSessionLocal()
    try:
        for tenant in cp_db.query(Tenant).filter(Tenant.status != "deleted").all():
            out.setdefault(admin_dsn_for(cp_db, tenant), []).append(tenant.slug)
    finally:
        cp_db.close()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="backup_tenants")
    parser.add_argument("--out", required=True)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if shutil.which("pg_dump") is None and not args.dry_run:
        print("error: pg_dump not on PATH", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / stamp
    failures = 0
    for dsn, names in targets().items():
        label = "_".join(names)[:80]
        target = run_dir / f"{label}.dump"
        print(f"{'would dump' if args.dry_run else 'dumping'} {label} -> {target}")
        if args.dry_run:
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(target), dsn], capture_output=True, text=True)
        if result.returncode != 0:
            failures += 1
            print(f"  FAILED: {result.stderr.strip()[-300:]}", file=sys.stderr)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
    for old in sorted(Path(args.out).glob("*T*Z")) if Path(args.out).exists() else []:
        try:
            taken = datetime.strptime(old.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if taken < cutoff:
            print(f"{'would prune' if args.dry_run else 'pruning'} {old}")
            if not args.dry_run:
                shutil.rmtree(old)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
