"""hrctl migrate --all-tenants [--parallel N] (docs/HRMS_COMPLETE_SPEC.txt Part 13 section B).

Upgrades every tenant database (and the control plane first, with --control-plane).
Expand/contract discipline (section C) is what makes running this while the previous app
version is still serving safe: a release's migration only ADDS; the matching removal
ships one release later.

    python -m hrctl.migrate --all-tenants [--parallel 4] [--control-plane]
"""

import argparse
import subprocess
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl migrate")
    parser.add_argument("--all-tenants", action="store_true", required=True)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--control-plane", action="store_true")
    args = parser.parse_args(argv)

    from app.platform.tenancy.provisioning import BACKEND_ROOT, migrate_all

    if args.control_plane:
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic_control_plane.ini", "upgrade", "head"], cwd=BACKEND_ROOT)
        if result.returncode != 0:
            print("control-plane migration failed", file=sys.stderr)
            return result.returncode
    results = migrate_all(parallel=args.parallel)
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
