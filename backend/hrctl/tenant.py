"""hrctl tenant <command> (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 3, Part 13 section B).

`bootstrap-existing` (Part 2) moves the original single-installation data into tenant #1.
Part 13 adds the full lifecycle (see hrctl/provisioning.py):

    python -m hrctl.tenant bootstrap-existing --slug <slug> --name "<name>" [--dry-run]
    python -m hrctl.tenant create --slug <slug> --name "<name>" [--plan <code>] [--isolation dedicated_db|shared_rls]
                                  [--region ap-south-1] [--admin-email <email>] [--domain <host>] [--config-pack <file>] [--dry-run]
    python -m hrctl.tenant suspend|resume|archive --slug <slug> [--reason "..."]
    python -m hrctl.tenant delete --slug <slug> [--confirm <slug>] [--drop-database]   (report only without --confirm)
    python -m hrctl.tenant export --slug <slug> --out <file.zip>
    python -m hrctl.tenant import --file <file.zip> [--isolation ...] [--region ...] [--dry-run]
"""

import argparse
import sys

from sqlalchemy import create_engine, text as sa_text

from app.core.config import settings
from app.core.database import SessionLocal
from app.platform.secrets.store import get_secret_store
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import ControlPlaneSecret, ControlPlaneSecretScope, Tenant

CONTROL_PLANE_SECRET_SCOPE = "control_plane"
TENANT_1_DSN_SECRET_REF = "tenant-1-db-dsn"

# Every tenant-owned table (see the tenant_id migration this depends on having already run)
# -- printed by --dry-run so an operator can see exactly what's about to become tenant #1's
# data before anything is written to the control plane.
TENANT_TABLES = (
    "applications", "audit_log", "bgv_documents", "candidates", "hr_inbound_emails",
    "hr_integrations", "interviews", "interview_confirmation_tokens",
    "interview_scheduling_settings", "job_roles", "local_import_settings",
    "negotiation_tokens", "offers", "screening_settings", "users", "user_integrations",
)


def _print_row_counts() -> None:
    # The admin DSN (a Postgres superuser locally), NOT settings.APP_DATABASE_URL -- that
    # connects as the non-superuser, RLS-subject app role, which would see zero rows here
    # regardless of how much real data exists, since app.tenant_id isn't set to anything on
    # this ad-hoc connection (see app.platform.tenancy.rls's own comment on the fail-closed
    # default for an unset session). Inspecting what's about to become tenant #1's data is
    # exactly the one legitimate reason to bypass RLS via the admin role here.
    admin_engine = create_engine(settings.DATABASE_URL)
    with admin_engine.connect() as conn:
        print("Row counts that will become tenant #1's data:")
        for table in TENANT_TABLES:
            count = conn.execute(sa_text(f'SELECT count(*) FROM "{table}"')).scalar()
            print(f"  {table}: {count}")


def bootstrap_existing(slug: str, name: str, dry_run: bool) -> None:
    _print_row_counts()
    if dry_run:
        print("\n--dry-run: nothing written. Re-run without --dry-run to create tenant #1.")
        return

    cp_db = ControlPlaneSessionLocal()
    try:
        existing = cp_db.get(Tenant, TENANT_1_ID)
        if existing is not None:
            print(f"Tenant #1 already exists in the control plane (slug={existing.slug!r}) -- skipping tenant-row creation.")
        else:
            store = get_secret_store(cp_db, ControlPlaneSecret, ControlPlaneSecretScope, CONTROL_PLANE_SECRET_SCOPE)
            try:
                store.get(TENANT_1_DSN_SECRET_REF)
            except Exception:
                store.put(TENANT_1_DSN_SECRET_REF, settings.APP_DATABASE_URL, created_by="hrctl")

            tenant = Tenant(
                id=TENANT_1_ID,
                slug=slug,
                display_name=name,
                status="active",
                isolation="dedicated_db",
                db_dsn_secret_ref=TENANT_1_DSN_SECRET_REF,
                region="ap-south-1",
                data_residency="IN",
            )
            cp_db.add(tenant)
            cp_db.commit()
            print(f"\nCreated tenant #1: slug={slug!r}, name={name!r}, id={TENANT_1_ID}")
    finally:
        cp_db.close()

    # Runs regardless of whether the tenant row above was newly created or already existed
    # -- SettingsService.set() is idempotent (an update, not a duplicate insert), so
    # re-running bootstrap-existing safely re-syncs the name if --name ever changes.
    # org.display_name/org.legal_name's registered default is deliberately generic (see
    # bootstrap_definitions.py's own comment) -- tenant #1's real name is DATA, seeded here
    # as an actual tenant-scoped setting_values row from --name, the same way it would be
    # for any other tenant, never baked into the schema's own default.
    register_settings_definitions()
    with tenant_context(TENANT_1_ID):
        tenant_db = SessionLocal()
        try:
            tenant_ctx = TenantContext(tenant_id=TENANT_1_ID, slug=slug, isolation="dedicated_db")
            service = SettingsService(tenant_db)
            for key in ("org.display_name", "org.legal_name"):
                service.set(key, name, scope_type="tenant", scope_id=None, actor="hrctl", tenant=tenant_ctx)
            print(f"Seeded org.display_name / org.legal_name = {name!r} for tenant #1.")
        finally:
            tenant_db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl tenant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap-existing")
    bootstrap.add_argument("--slug", required=True)
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--dry-run", action="store_true")

    # ---- Part 13 lifecycle (logic in hrctl/provisioning.py, shared with the Super-Admin console) ----
    create = subparsers.add_parser("create")
    create.add_argument("--slug", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--plan")
    create.add_argument("--isolation", default="dedicated_db", choices=("dedicated_db", "shared_rls"))
    create.add_argument("--region", default="ap-south-1")
    create.add_argument("--admin-email")
    create.add_argument("--domain")
    create.add_argument("--config-pack")
    create.add_argument("--dry-run", action="store_true")

    for name in ("suspend", "resume", "archive"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--slug", required=True)
        sub.add_argument("--reason")

    delete = subparsers.add_parser("delete")
    delete.add_argument("--slug", required=True)
    delete.add_argument("--confirm", help="repeat the slug to actually delete; without it only a report is printed")
    delete.add_argument("--drop-database", action="store_true")

    export = subparsers.add_parser("export")
    export.add_argument("--slug", required=True)
    export.add_argument("--out", required=True)

    imp = subparsers.add_parser("import")
    imp.add_argument("--file", required=True)
    imp.add_argument("--isolation", default="dedicated_db", choices=("dedicated_db", "shared_rls"))
    imp.add_argument("--region")
    imp.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "bootstrap-existing":
        bootstrap_existing(args.slug, args.name, args.dry_run)
        return 0

    import json

    from app.platform.tenancy import provisioning

    try:
        if args.command == "create":
            pack = json.loads(open(args.config_pack, encoding="utf-8").read()) if args.config_pack else None
            result = provisioning.create_tenant(slug=args.slug, name=args.name, isolation=args.isolation, region=args.region, plan_code=args.plan,
                                                admin_email=args.admin_email, domain=args.domain, config_pack=pack, dry_run=args.dry_run)
        elif args.command in ("suspend", "resume", "archive"):
            status = {"suspend": "suspended", "resume": "active", "archive": "archived"}[args.command]
            result = provisioning.set_status(args.slug, status, reason=args.reason)
        elif args.command == "delete":
            result = provisioning.delete_tenant(args.slug, confirm=args.confirm, drop_database=args.drop_database)
        elif args.command == "export":
            result = provisioning.export_tenant(args.slug, args.out)
        else:
            result = provisioning.import_tenant(args.file, isolation=args.isolation, region=args.region, dry_run=args.dry_run)
    except provisioning.ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
