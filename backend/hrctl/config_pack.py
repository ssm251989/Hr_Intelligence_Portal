"""hrctl config-pack export|import (docs/HRMS_COMPLETE_SPEC.txt Part 13 section B) -- see
app/platform/config_pack.py for what a pack contains and how ids are remapped.

    python -m hrctl.config_pack export --slug <tenant> --out pack.json
    python -m hrctl.config_pack import --slug <tenant> --file pack.json [--dry-run]
"""

import argparse
import json
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl config-pack")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--slug", required=True)
    exp.add_argument("--out", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("--slug", required=True)
    imp.add_argument("--file", required=True)
    imp.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from app.platform import config_pack
    from app.platform.settings.bootstrap_definitions import register_all
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    register_all()
    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).filter(Tenant.slug == args.slug).first()
    finally:
        cp_db.close()
    if tenant is None:
        print(f"error: no tenant {args.slug!r}", file=sys.stderr)
        return 2
    ctx = TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)
    with tenant_context(tenant.id):
        db = tenant_session(tenant)
        try:
            if args.command == "export":
                pack = config_pack.export_pack(db, ctx)
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(config_pack.dumps(pack))
                print(json.dumps({"written": args.out, "tables": {k: len(v) for k, v in pack["tables"].items()}}, indent=2))
            else:
                with open(args.file, encoding="utf-8") as fh:
                    pack = json.load(fh)
                print(json.dumps(config_pack.import_pack(db, ctx, pack, actor="hrctl", dry_run=args.dry_run), indent=2, default=str))
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
